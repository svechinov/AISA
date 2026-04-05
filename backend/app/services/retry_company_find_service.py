"""Re-run find_contacts for one collected company; merge results and re-validate + persist contacts."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.models.step import Step
from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import get_company_dict_at_index, list_run_companies_sparse
from app.repositories.step_repo import create_step, get_step_by_run_and_name, mark_step_completed
from app.services.contact_persistence_service import (
    contacts_raw_for_pipeline_dicts,
    persist_validated_contacts,
)
from app.services.orchestrator import _merge_contacts
from app.services.run_companies_status_service import _contact_matches_company, _entity_keys
from app.workers.contacts_worker import find_contacts, validate_contacts

_RETRY_LOCK_GUARD = threading.Lock()
_RETRY_LOCKS_BY_RUN: dict[int, threading.Lock] = {}


def _retry_serial_lock(run_id: int) -> threading.Lock:
    """Serialize merge/persist for one run when DB row locks are unreliable (SQLite; single process)."""
    with _RETRY_LOCK_GUARD:
        lk = _RETRY_LOCKS_BY_RUN.get(run_id)
        if lk is None:
            lk = threading.Lock()
            _RETRY_LOCKS_BY_RUN[run_id] = lk
        return lk


def _session_is_sqlite(db: Session) -> bool:
    return db.get_bind().dialect.name == "sqlite"


def continue_find_for_pending_companies(db: Session, run_id: int) -> dict:
    """
    For runs where find_contacts is not completed, run find once for every collected company
    that still has no matching contact in the find output. Then mark find (and validate) completed.

    We only require at least one company row in run_companies. Matches Companies UI \"Not searched yet\" (find not completed).
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")

    step_collect = get_step_by_run_and_name(db, run_id, "collect_companies")
    step_find = get_step_by_run_and_name(db, run_id, "find_contacts")

    if not step_collect:
        raise ValueError("Collect companies step not found")
    if step_collect.status == "failed":
        raise ValueError("Collect companies step failed — fix the run and try again")

    raw_companies = list_run_companies_sparse(db, run_id)
    if not isinstance(raw_companies, list) or not any(isinstance(c, dict) for c in raw_companies):
        raise ValueError(
            "No companies stored for this run yet — wait until search has added at least one company",
        )

    find_completed = bool(step_find and step_find.status == "completed")
    if find_completed:
        raise ValueError("Find contacts step is already completed")

    raw_contacts = contacts_raw_for_pipeline_dicts(db, run_id)

    pending_companies: list[dict] = []
    for co in raw_companies:
        if not isinstance(co, dict):
            continue
        if co.get("llm_hallucination") is True:
            continue
        ckeys = _entity_keys(co)
        has_contact = any(
            isinstance(ct, dict) and _contact_matches_company(ct, ckeys) for ct in raw_contacts
        )
        if not has_contact:
            pending_companies.append(co)

    if not pending_companies:
        if not step_find:
            step_find = create_step(db, run_id, "find_contacts", {}, commit=True)
        mark_step_completed(
            db,
            step_find,
            {"contacts_count": len(raw_contacts)},
            commit=True,
        )
        vin = {"contacts": raw_contacts}
        last_validate = validate_contacts(db, run_id, run.workflow_name, vin)
        st_v = get_step_by_run_and_name(db, run_id, "validate_contacts")
        if not st_v:
            st_v = create_step(db, run_id, "validate_contacts", vin, commit=True)
        mark_step_completed(
            db,
            st_v,
            {
                "valid_count": len(last_validate.get("valid_contacts") or []),
                "invalid_count": len(last_validate.get("invalid_contacts") or []),
            },
            commit=True,
        )
        persist_validated_contacts(db, run_id, last_validate, commit=True)
        return {
            "contacts_before": len(raw_contacts),
            "contacts_after": len(raw_contacts),
            "new_contacts_merged": 0,
        }

    if not step_find:
        create_step(db, run_id, "find_contacts", {}, commit=True)

    out_new = find_contacts(
        db,
        run_id,
        run.workflow_name,
        {"companies": pending_companies},
    )
    batch = out_new.get("contacts") if isinstance(out_new.get("contacts"), list) else []

    if _session_is_sqlite(db):
        with _retry_serial_lock(run_id):
            return _merge_validate_persist_locked(
                db,
                run_id,
                run.workflow_name,
                batch,
                use_row_lock=False,
            )
    return _merge_validate_persist_locked(
        db,
        run_id,
        run.workflow_name,
        batch,
        use_row_lock=True,
    )


def retry_find_for_collected_company(db: Session, run_id: int, collect_index: int) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")

    step_collect = get_step_by_run_and_name(db, run_id, "collect_companies")
    step_find_ref = get_step_by_run_and_name(db, run_id, "find_contacts")
    step_validate_ref = get_step_by_run_and_name(db, run_id, "validate_contacts")

    if not step_collect or step_collect.status != "completed":
        raise ValueError("Collect companies step is not completed yet")
    if not step_find_ref or step_find_ref.status != "completed":
        raise ValueError("Find contacts step is not completed yet — retry when setup has finished")

    company_row = get_company_dict_at_index(db, run_id, collect_index)
    if not company_row:
        raise ValueError("Invalid company index")
    if company_row.get("llm_hallucination") is True:
        raise ValueError(
            "This company is marked LLM hallucination (invalid or unreachable website); contact search retry is disabled.",
        )

    # LLM call can run in parallel across requests; merge must see latest stored contacts.
    out_new = find_contacts(
        db,
        run_id,
        run.workflow_name,
        {"companies": [company_row]},
    )
    batch = out_new.get("contacts") if isinstance(out_new.get("contacts"), list) else []

    if _session_is_sqlite(db):
        with _retry_serial_lock(run_id):
            return _merge_validate_persist_locked(
                db,
                run_id,
                run.workflow_name,
                batch,
                use_row_lock=False,
            )
    return _merge_validate_persist_locked(
        db,
        run_id,
        run.workflow_name,
        batch,
        use_row_lock=True,
    )


def _merge_validate_persist_locked(
    db: Session,
    run_id: int,
    workflow_name: str,
    batch: list,
    *,
    use_row_lock: bool,
) -> dict:
    """
    Merge batch into contacts from DB, re-validate, persist (steps store counts only).
    When use_row_lock=True (Postgres, etc.), run in one transaction with FOR UPDATE.
    When False (SQLite under process lock), use normal commits after each repo call.
    """
    # Steps were likely loaded at the start of this request; after a slow LLM call another
    # request may have committed newer output_json. Expire cached ORM state so we always
    # merge against the latest DB row (avoids second Retry wiping the first).
    db.expire_all()

    if use_row_lock:
        try:
            step_find = (
                db.query(Step)
                .filter(Step.run_id == run_id, Step.step_name == "find_contacts")
                .with_for_update()
                .one()
            )
            step_validate = (
                db.query(Step)
                .filter(Step.run_id == run_id, Step.step_name == "validate_contacts")
                .with_for_update()
                .first()
            )
            existing = contacts_raw_for_pipeline_dicts(db, run_id)
            before = len(existing)
            merged = _merge_contacts(existing, batch)
            after = len(merged)

            mark_step_completed(
                db,
                step_find,
                {
                    "contacts_count": after,
                    "batch_size": len(batch),
                },
                commit=False,
            )

            vin = {"contacts": merged}
            last_validate = validate_contacts(db, run_id, workflow_name, vin)
            st_v = step_validate
            if not st_v:
                st_v = create_step(db, run_id, "validate_contacts", vin, commit=False)
            mark_step_completed(
                db,
                st_v,
                {
                    "valid_count": len(last_validate.get("valid_contacts") or []),
                    "invalid_count": len(last_validate.get("invalid_contacts") or []),
                },
                commit=False,
            )
            persist_validated_contacts(db, run_id, last_validate, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {
            "contacts_before": before,
            "contacts_after": after,
            "new_contacts_merged": after - before,
        }

    # SQLite (or other): process-level lock already held
    step_find = get_step_by_run_and_name(db, run_id, "find_contacts")
    if not step_find:
        raise ValueError("Find contacts step missing")
    existing = contacts_raw_for_pipeline_dicts(db, run_id)
    before = len(existing)
    merged = _merge_contacts(existing, batch)
    after = len(merged)

    mark_step_completed(
        db,
        step_find,
        {
            "contacts_count": after,
            "batch_size": len(batch),
        },
        commit=True,
    )

    vin = {"contacts": merged}
    last_validate = validate_contacts(db, run_id, workflow_name, vin)
    st_v = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st_v:
        st_v = create_step(db, run_id, "validate_contacts", vin, commit=True)
    mark_step_completed(
        db,
        st_v,
        {
            "valid_count": len(last_validate.get("valid_contacts") or []),
            "invalid_count": len(last_validate.get("invalid_contacts") or []),
        },
        commit=True,
    )
    persist_validated_contacts(db, run_id, last_validate, commit=True)

    return {
        "contacts_before": before,
        "contacts_after": after,
        "new_contacts_merged": after - before,
    }
