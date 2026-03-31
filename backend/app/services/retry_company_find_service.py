"""Re-run find_contacts for one collected company; merge results and re-validate + persist contacts."""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app.models.step import Step
from app.repositories.run_repo import get_run
from app.repositories.step_repo import create_step, get_step_by_run_and_name, mark_step_completed
from app.services.contact_persistence_service import persist_validated_contacts
from app.services.orchestrator import _merge_contacts
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

    out_c = step_collect.output_json if isinstance(step_collect.output_json, dict) else {}
    raw_companies = out_c.get("companies")
    if not isinstance(raw_companies, list):
        raise ValueError("No companies list on collect step")
    if collect_index < 0 or collect_index >= len(raw_companies):
        raise ValueError("Invalid company index")
    company_row = raw_companies[collect_index]
    if not isinstance(company_row, dict):
        raise ValueError("Company entry is not valid")

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
    Read latest find_contacts output, merge batch, re-validate, persist.
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
            out_f = step_find.output_json if isinstance(step_find.output_json, dict) else {}
            existing = out_f.get("contacts")
            if not isinstance(existing, list):
                existing = []
            before = len(existing)
            merged = _merge_contacts(existing, batch)
            after = len(merged)

            mark_step_completed(db, step_find, {"contacts": merged}, commit=False)

            vin = {"contacts": merged}
            last_validate = validate_contacts(db, run_id, workflow_name, vin)
            st_v = step_validate
            if not st_v:
                st_v = create_step(db, run_id, "validate_contacts", vin, commit=False)
            mark_step_completed(db, st_v, last_validate, commit=False)
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
    out_f = step_find.output_json if isinstance(step_find.output_json, dict) else {}
    existing = out_f.get("contacts")
    if not isinstance(existing, list):
        existing = []
    before = len(existing)
    merged = _merge_contacts(existing, batch)
    after = len(merged)

    mark_step_completed(db, step_find, {"contacts": merged}, commit=True)

    vin = {"contacts": merged}
    last_validate = validate_contacts(db, run_id, workflow_name, vin)
    st_v = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st_v:
        st_v = create_step(db, run_id, "validate_contacts", vin, commit=True)
    mark_step_completed(db, st_v, last_validate, commit=True)
    persist_validated_contacts(db, run_id, last_validate, commit=True)

    return {
        "contacts_before": before,
        "contacts_after": after,
        "new_contacts_merged": after - before,
    }
