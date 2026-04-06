from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run, update_run_status
from app.repositories.run_company_repo import list_run_companies_sparse, sync_run_companies_from_dicts
from app.repositories.step_repo import (
    create_step,
    get_step_by_run_and_name,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
    update_step_progress,
)
from app.services.contact_persistence_service import (
    contacts_raw_for_pipeline_dicts,
    persist_validated_contacts,
)
from app.utils.contact_identity import contact_identity_key_from_dict
from app.services.email_draft_persistence_service import persist_generated_emails
from app.services.run_context_service import build_collect_companies_input_for_round
from app.services.workflow_registry import WORKFLOWS
from app.setup_milestones import (
    CONTINUE_OUTREACH_MIN_ROUNDS,
    CONTINUE_OUTREACH_STALL_LIMIT,
    SETUP_ACCUMULATION_MAX_ROUNDS,
    SETUP_EXTRA_ROUNDS_AFTER_MILESTONES,
    SETUP_MILESTONE_COMPANIES,
    SETUP_MILESTONE_CONTACTS,
    SETUP_MILESTONE_VALID_CONTACTS,
    SETUP_STALL_LIMIT_DEFAULT,
)
from app.workers.contacts_worker import find_contacts, validate_contacts
from app.workers.email_worker import generate_emails, generate_master_email_draft
from app.workers.research_worker import collect_companies

STEP_HANDLERS = {
    "collect_companies": collect_companies,
    "find_contacts": find_contacts,
    "validate_contacts": validate_contacts,
    "generate_master_email_draft": generate_master_email_draft,
    "generate_emails": generate_emails,
}


def get_workflow_steps(workflow_name: str) -> list[str]:
    if workflow_name not in WORKFLOWS:
        raise ValueError(f"Unknown workflow: {workflow_name}")
    return WORKFLOWS[workflow_name]


def _company_key(c: dict) -> str:
    w = (c.get("website") or "").strip().lower()
    if w:
        return w
    return (c.get("name") or "").strip().lower()


def _merge_companies(existing: list[dict], new_items: list) -> list[dict]:
    seen = {_company_key(c) for c in existing if _company_key(c)}
    out = list(existing)
    for c in new_items:
        if not isinstance(c, dict):
            continue
        k = _company_key(c)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def _contact_email_norm(c: dict) -> str:
    return (c.get("email") or "").strip().lower()


def _merge_contacts(existing: list[dict], new_items: list) -> list[dict]:
    """Append new contacts; dedupe by email, or by name+company+website when email is missing."""
    seen_emails: set[str] = set()
    seen_no_email_id: set[str] = set()
    identities_with_email: set[str] = set()
    for c in existing:
        if not isinstance(c, dict):
            continue
        em = _contact_email_norm(c)
        if em and "@" in em:
            seen_emails.add(em)
            ik = contact_identity_key_from_dict(c)
            if ik:
                identities_with_email.add(ik)
            continue
        ik = contact_identity_key_from_dict(c)
        if ik:
            seen_no_email_id.add(ik)
    out = list(existing)
    for c in new_items:
        if not isinstance(c, dict):
            continue
        em = _contact_email_norm(c)
        if em and "@" in em:
            if em in seen_emails:
                continue
            seen_emails.add(em)
            ik = contact_identity_key_from_dict(c)
            if ik:
                identities_with_email.add(ik)
            out.append(c)
            continue
        ik = contact_identity_key_from_dict(c)
        if ik and ik in identities_with_email:
            continue
        if ik and ik in seen_no_email_id:
            continue
        if ik:
            seen_no_email_id.add(ik)
        out.append(c)

    # Drop accumulated no-email rows once the same person (name+company+website) has an email.
    iw: set[str] = set()
    for c in out:
        if not isinstance(c, dict):
            continue
        em = _contact_email_norm(c)
        if em and "@" in em:
            ik = contact_identity_key_from_dict(c)
            if ik:
                iw.add(ik)
    cleaned: list[dict] = []
    for c in out:
        if not isinstance(c, dict):
            continue
        em = _contact_email_norm(c)
        if em and "@" in em:
            cleaned.append(c)
            continue
        ik = contact_identity_key_from_dict(c)
        if ik and ik in iw:
            continue
        cleaned.append(c)
    return cleaned


def _load_accumulating_setup_seed(db: Session, run_id: int) -> tuple[list[dict], list[dict]]:
    """Restore in-memory setup state from run_companies + contacts table (not step JSON)."""
    raw_co = list_run_companies_sparse(db, run_id)
    companies = [x for x in raw_co if isinstance(x, dict)]
    contacts = contacts_raw_for_pipeline_dicts(db, run_id)

    if not companies and contacts:
        seen: set[str] = set()
        for co in contacts:
            k = _company_key(co)
            if not k or k in seen:
                continue
            seen.add(k)
            nm = (co.get("company") or "").strip() or (co.get("name") or "").strip()
            companies.append(
                {
                    "name": nm,
                    "website": (co.get("website") or "").strip(),
                }
            )

    return companies, contacts


def _ensure_step(db: Session, run_id: int, step_name: str):
    s = get_step_by_run_and_name(db, run_id, step_name)
    return s if s else create_step(db, run_id, step_name, {})


def run_accumulating_setup_phase(db: Session, run_id: int, *, continuation: bool = False) -> None:
    """
    Repeatedly collect → find → validate until enough valid contacts (or stall / max rounds).
    Step rows stay running with growing output_json until the phase finishes, then all three complete.

    continuation=True (Continue outreach / POST /runs/:id/restart): prioritize "gather more" —
    do not stop early just because milestones were already met; require more rounds before
    stall-based exit and use a higher stall threshold.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    companies, contacts = _load_accumulating_setup_seed(db, run_id)

    step_c = _ensure_step(db, run_id, "collect_companies")
    step_f = _ensure_step(db, run_id, "find_contacts")
    step_v = _ensure_step(db, run_id, "validate_contacts")

    prev_sig: tuple[int, int, int] | None = None
    stall = 0
    round_idx = 0
    rounds_after_all_milestones = 0
    last_validate: dict = {"valid_contacts": [], "invalid_contacts": []}

    while round_idx < SETUP_ACCUMULATION_MAX_ROUNDS:
        run = get_run(db, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        cin = build_collect_companies_input_for_round(
            run, companies, round_idx, continuation=continuation
        )
        mark_step_running(db, step_c, cin)
        try:
            out_c = collect_companies(db, run_id, run.workflow_name, cin)
        except Exception as e:
            mark_step_failed(db, step_c, str(e))
            raise
        batch_c = out_c.get("companies") if isinstance(out_c.get("companies"), list) else []
        companies = _merge_companies(companies, batch_c)
        sync_run_companies_from_dicts(db, run_id, companies, commit=False)
        update_step_progress(db, step_c, {})

        fin = {}
        mark_step_running(db, step_f, fin)
        try:
            out_f = find_contacts(db, run_id, run.workflow_name, fin)
        except Exception as e:
            mark_step_failed(db, step_f, str(e))
            raise
        batch_f = out_f.get("contacts") if isinstance(out_f.get("contacts"), list) else []
        contacts = _merge_contacts(contacts, batch_f)
        update_step_progress(db, step_f, {"contacts_count": len(contacts)})

        vin = {"contacts": contacts}
        mark_step_running(db, step_v, vin)
        try:
            last_validate = validate_contacts(db, run_id, run.workflow_name, vin)
        except Exception as e:
            mark_step_failed(db, step_v, str(e))
            raise
        update_step_progress(
            db,
            step_v,
            {
                "valid_count": len(last_validate.get("valid_contacts") or []),
                "invalid_count": len(last_validate.get("invalid_contacts") or []),
            },
        )
        persist_validated_contacts(db, run_id, last_validate)

        valid_n = len(last_validate.get("valid_contacts") or [])
        sig = (len(companies), len(contacts), valid_n)
        stall_limit = CONTINUE_OUTREACH_STALL_LIMIT if continuation else SETUP_STALL_LIMIT_DEFAULT
        if continuation and round_idx < CONTINUE_OUTREACH_MIN_ROUNDS:
            stall = 0
            prev_sig = sig
        elif prev_sig == sig:
            stall += 1
            if stall >= stall_limit:
                break
        else:
            stall = 0
            prev_sig = sig

        all_milestones = (
            len(companies) >= SETUP_MILESTONE_COMPANIES
            and len(contacts) >= SETUP_MILESTONE_CONTACTS
            and valid_n >= SETUP_MILESTONE_VALID_CONTACTS
        )
        if all_milestones:
            rounds_after_all_milestones += 1
            if rounds_after_all_milestones > SETUP_EXTRA_ROUNDS_AFTER_MILESTONES:
                if not continuation:
                    break
        else:
            rounds_after_all_milestones = 0

        round_idx += 1

    sync_run_companies_from_dicts(db, run_id, companies, commit=False)
    mark_step_completed(db, step_c, {})
    mark_step_completed(
        db,
        step_f,
        {
            "contacts_count": len(contacts),
        },
    )
    mark_step_completed(
        db,
        step_v,
        {
            "valid_count": len(last_validate.get("valid_contacts") or []),
            "invalid_count": len(last_validate.get("invalid_contacts") or []),
        },
    )


def build_step_input(db: Session, run_id: int, step_name: str) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    workflow_steps = get_workflow_steps(run.workflow_name)
    step_index = workflow_steps.index(step_name)

    if step_index == 0:
        from app.services.run_context_service import build_pack_step_zero_input

        return build_pack_step_zero_input(run)

    previous_step_name = workflow_steps[step_index - 1]
    previous_step = get_step_by_run_and_name(db, run_id, previous_step_name)

    if not previous_step:
        raise ValueError(f"Previous step {previous_step_name} not found")

    if previous_step_name == "collect_companies":
        return {}

    if previous_step_name == "find_contacts":
        return {}

    from app.utils.step_payload import effective_step_output_json

    return effective_step_output_json(db, previous_step) or {}


def execute_step(db: Session, run_id: int, step_name: str):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    step = get_step_by_run_and_name(db, run_id, step_name)
    if not step:
        step = create_step(db, run_id, step_name, {})

    step_input = build_step_input(db, run_id, step_name)
    mark_step_running(db, step, step_input)

    handler = STEP_HANDLERS[step_name]

    try:
        output = handler(
            db=db,
            run_id=run_id,
            workflow_name=run.workflow_name,
            step_input=step_input,
        )
        if step_name == "collect_companies" and isinstance(output, dict):
            sync_run_companies_from_dicts(
                db,
                run_id,
                output.get("companies") if isinstance(output.get("companies"), list) else [],
                commit=False,
            )
            output = {}
        if step_name == "find_contacts" and isinstance(output, dict):
            batch = output.get("contacts") if isinstance(output.get("contacts"), list) else []
            existing = contacts_raw_for_pipeline_dicts(db, run_id)
            merged = _merge_contacts(existing, batch)
            last_v = validate_contacts(db, run_id, run.workflow_name, {"contacts": merged})
            persist_validated_contacts(db, run_id, last_v, commit=False)
            output = {
                "batch_size": len(batch),
                "merged_total": len(merged),
                "valid_count": len(last_v.get("valid_contacts") or []),
                "invalid_count": len(last_v.get("invalid_contacts") or []),
            }
        if step_name == "validate_contacts" and isinstance(output, dict):
            persist_validated_contacts(db, run_id, output, commit=False)
            output = {
                "valid_count": len(output.get("valid_contacts") or []),
                "invalid_count": len(output.get("invalid_contacts") or []),
            }
        mark_step_completed(db, step, output)

        if step_name == "generate_emails":
            persist_generated_emails(db, run_id, output)

    except Exception as e:
        mark_step_failed(db, step, str(e))
        raise


def run_workflow(db: Session, run_id: int, *, continuation: bool = False):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    update_run_status(db, run, "running")

    try:
        run_accumulating_setup_phase(db, run_id, continuation=continuation)
        run = get_run(db, run_id)
        update_run_status(db, run, "needs_review")
        return
    except Exception:
        run = get_run(db, run_id)
        update_run_status(db, run, "failed")
        raise


def continue_workflow_after_review(db: Session, run_id: int):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    if run.status != "needs_review":
        raise ValueError(f"Run {run_id} is not waiting for review")

    update_run_status(db, run, "running")

    try:
        run = get_run(db, run_id)
        if not (list(getattr(run, "master_email_variants", None) or []) if run else []):
            execute_step(db, run_id, "generate_master_email_draft")
        execute_step(db, run_id, "generate_emails")
        run = get_run(db, run_id)
        update_run_status(db, run, "drafts_ready")
    except Exception:
        run = get_run(db, run_id)
        update_run_status(db, run, "failed")
        raise
