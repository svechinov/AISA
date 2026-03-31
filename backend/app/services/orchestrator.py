from sqlalchemy.orm import Session

from app.repositories.contact_repo import list_contacts_by_run
from app.repositories.run_repo import get_run, update_run_status
from app.repositories.step_repo import (
    create_step,
    get_step_by_run_and_name,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
    update_step_progress,
)
from app.services.contact_persistence_service import persist_validated_contacts
from app.services.email_draft_persistence_service import persist_generated_emails
from app.services.run_context_service import build_collect_companies_input_for_round
from app.services.workflow_registry import WORKFLOWS
from app.setup_milestones import (
    SETUP_ACCUMULATION_MAX_ROUNDS,
    SETUP_EXTRA_ROUNDS_AFTER_MILESTONES,
    SETUP_MILESTONE_COMPANIES,
    SETUP_MILESTONE_CONTACTS,
    SETUP_MILESTONE_VALID_CONTACTS,
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
    """Append new contacts; skip when normalized email already present (ignore company spelling drift)."""
    seen_emails: set[str] = set()
    for c in existing:
        em = _contact_email_norm(c)
        if em and "@" in em:
            seen_emails.add(em)
    out = list(existing)
    for c in new_items:
        if not isinstance(c, dict):
            continue
        em = _contact_email_norm(c)
        if em and "@" in em:
            if em in seen_emails:
                continue
            seen_emails.add(em)
        out.append(c)
    return out


def _dicts_from_step_output(step, key: str) -> list[dict]:
    if not step or not isinstance(step.output_json, dict):
        return []
    raw = step.output_json.get(key)
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _load_accumulating_setup_seed(db: Session, run_id: int) -> tuple[list[dict], list[dict], dict]:
    """Restore in-memory setup state from step outputs and/or existing contacts (restart / extra rounds)."""
    step_c = get_step_by_run_and_name(db, run_id, "collect_companies")
    step_f = get_step_by_run_and_name(db, run_id, "find_contacts")
    step_v = get_step_by_run_and_name(db, run_id, "validate_contacts")

    companies = _dicts_from_step_output(step_c, "companies")
    contacts = _dicts_from_step_output(step_f, "contacts")

    last_validate: dict = {"valid_contacts": [], "invalid_contacts": []}
    if step_v and isinstance(step_v.output_json, dict):
        vc = step_v.output_json.get("valid_contacts")
        ic = step_v.output_json.get("invalid_contacts")
        if isinstance(vc, list):
            last_validate["valid_contacts"] = [x for x in vc if isinstance(x, dict)]
        if isinstance(ic, list):
            last_validate["invalid_contacts"] = [x for x in ic if isinstance(x, dict)]

    if not contacts:
        for c in list_contacts_by_run(db, run_id):
            row = {
                "company": c.company,
                "website": c.website,
                "name": c.name,
                "role": c.role,
                "email": c.email,
                "linkedin": c.linkedin,
                "confidence": c.confidence,
            }
            sj = c.source_json if isinstance(c.source_json, dict) else {}
            contacts.append({**sj, **{k: v for k, v in row.items() if v is not None}})

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

    return companies, contacts, last_validate


def _ensure_step(db: Session, run_id: int, step_name: str):
    s = get_step_by_run_and_name(db, run_id, step_name)
    return s if s else create_step(db, run_id, step_name, {})


def run_accumulating_setup_phase(db: Session, run_id: int) -> None:
    """
    Repeatedly collect → find → validate until enough valid contacts (or stall / max rounds).
    Step rows stay running with growing output_json until the phase finishes, then all three complete.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    companies, contacts, last_validate = _load_accumulating_setup_seed(db, run_id)

    step_c = _ensure_step(db, run_id, "collect_companies")
    step_f = _ensure_step(db, run_id, "find_contacts")
    step_v = _ensure_step(db, run_id, "validate_contacts")

    prev_sig: tuple[int, int, int] | None = None
    stall = 0
    round_idx = 0
    rounds_after_all_milestones = 0

    while round_idx < SETUP_ACCUMULATION_MAX_ROUNDS:
        run = get_run(db, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        cin = build_collect_companies_input_for_round(run, companies, round_idx)
        mark_step_running(db, step_c, cin)
        try:
            out_c = collect_companies(db, run_id, run.workflow_name, cin)
        except Exception as e:
            mark_step_failed(db, step_c, str(e))
            raise
        batch_c = out_c.get("companies") if isinstance(out_c.get("companies"), list) else []
        companies = _merge_companies(companies, batch_c)
        update_step_progress(db, step_c, {"companies": companies})

        fin = {"companies": companies}
        mark_step_running(db, step_f, fin)
        try:
            out_f = find_contacts(db, run_id, run.workflow_name, fin)
        except Exception as e:
            mark_step_failed(db, step_f, str(e))
            raise
        batch_f = out_f.get("contacts") if isinstance(out_f.get("contacts"), list) else []
        contacts = _merge_contacts(contacts, batch_f)
        update_step_progress(db, step_f, {"contacts": contacts})

        vin = {"contacts": contacts}
        mark_step_running(db, step_v, vin)
        try:
            last_validate = validate_contacts(db, run_id, run.workflow_name, vin)
        except Exception as e:
            mark_step_failed(db, step_v, str(e))
            raise
        update_step_progress(db, step_v, last_validate)
        persist_validated_contacts(db, run_id, last_validate)

        valid_n = len(last_validate.get("valid_contacts") or [])
        sig = (len(companies), len(contacts), valid_n)
        if prev_sig == sig:
            stall += 1
            if stall >= 2:
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
                break
        else:
            rounds_after_all_milestones = 0

        round_idx += 1

    mark_step_completed(db, step_c, {"companies": companies})
    mark_step_completed(db, step_f, {"contacts": contacts})
    mark_step_completed(db, step_v, last_validate)


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

    return previous_step.output_json or {}


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
        mark_step_completed(db, step, output)

        if step_name == "validate_contacts":
            persist_validated_contacts(db, run_id, output)

        if step_name == "generate_emails":
            persist_generated_emails(db, run_id, output)

    except Exception as e:
        mark_step_failed(db, step, str(e))
        raise


def run_workflow(db: Session, run_id: int):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    update_run_status(db, run, "running")

    try:
        run_accumulating_setup_phase(db, run_id)
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
        if not (run.master_email if run else None):
            execute_step(db, run_id, "generate_master_email_draft")
        execute_step(db, run_id, "generate_emails")
        run = get_run(db, run_id)
        update_run_status(db, run, "drafts_ready")
    except Exception:
        run = get_run(db, run_id)
        update_run_status(db, run, "failed")
        raise
