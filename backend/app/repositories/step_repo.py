from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_STEP_INPUT, SCOPE_STEP_OUTPUT
from app.models.entity_json_kv import EntityJsonKV
from app.models.step import Step
from app.utils.step_payload import persist_step_input, persist_step_output


def get_collect_and_find_steps_meta(db: Session, run_id: int) -> dict[str, Any]:
    """One round-trip: ids + statuses for collect_companies and find_contacts (Human UI GET /runs/:id/companies)."""
    rows = (
        db.query(Step.id, Step.step_name, Step.status)
        .filter(
            Step.run_id == run_id,
            Step.step_name.in_(("collect_companies", "find_contacts")),
        )
        .order_by(Step.id.asc())
        .all()
    )
    out: dict[str, Any] = {
        "collect_step_id": None,
        "find_step_id": None,
        "collect_status": None,
        "find_status": None,
    }
    seen: set[str] = set()
    for sid, name, status in rows:
        if name in seen:
            continue
        seen.add(name)
        if name == "collect_companies":
            out["collect_step_id"] = sid
            out["collect_status"] = status
        elif name == "find_contacts":
            out["find_step_id"] = sid
            out["find_status"] = status
    return out


def get_step_status_by_run_and_name(db: Session, run_id: int, step_name: str) -> str | None:
    """Step status only — avoids loading input/output JSON."""
    return db.execute(
        select(Step.status).where(Step.run_id == run_id, Step.step_name == step_name)
    ).scalar_one_or_none()


def get_step_id_by_run_and_name(db: Session, run_id: int, step_name: str) -> int | None:
    return db.execute(
        select(Step.id).where(Step.run_id == run_id, Step.step_name == step_name)
    ).scalar_one_or_none()


def _contact_lite_dict(ct: dict) -> dict:
    """Minimal fields for company↔contact key matching (see run_companies_status_service)."""
    return {"name": ct.get("name"), "website": ct.get("website"), "email": ct.get("email")}


def get_find_contacts_for_matching(
    db: Session,
    run_id: int,
    *,
    limit: int | None = None,
) -> tuple[list[dict], str]:
    """Contacts as name/website/email only — canonical ``contacts`` table (not step JSON)."""
    from app.models.contact import Contact

    q = (
        db.query(Contact.name, Contact.website, Contact.email)
        .filter(Contact.run_id == run_id)
        .order_by(Contact.id.asc())
    )
    if limit is not None:
        q = q.limit(max(1, int(limit)))
    rows = q.all()
    out: list[dict] = []
    for name, website, email in rows:
        out.append(_contact_lite_dict({"name": name, "website": website, "email": email}))
    tag = "contacts_table" if limit is None else f"contacts_table_limit_{limit}"
    return out, tag


def create_step(
    db: Session,
    run_id: int,
    step_name: str,
    input_json: dict,
    *,
    commit: bool = True,
) -> Step:
    step = Step(
        run_id=run_id,
        step_name=step_name,
        status="pending",
        input_json={},
        output_json={},
    )
    db.add(step)
    if commit:
        db.flush()
        persist_step_input(db, step, input_json)
        db.commit()
        db.refresh(step)
    else:
        db.flush()
        persist_step_input(db, step, input_json)
        db.refresh(step)
    return step


def list_steps_by_run(db: Session, run_id: int) -> list[Step]:
    return (
        db.query(Step)
        .filter(Step.run_id == run_id)
        .order_by(Step.id.asc())
        .all()
    )


def delete_steps_by_run(db: Session, run_id: int) -> int:
    step_ids = [r[0] for r in db.query(Step.id).filter(Step.run_id == run_id).all()]
    if step_ids:
        db.query(EntityJsonKV).filter(
            EntityJsonKV.scope.in_([SCOPE_STEP_INPUT, SCOPE_STEP_OUTPUT]),
            EntityJsonKV.entity_id.in_(step_ids),
        ).delete(synchronize_session=False)
    q = db.query(Step).filter(Step.run_id == run_id)
    n = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return n


def get_step(db: Session, step_id: int) -> Step | None:
    return db.query(Step).filter(Step.id == step_id).first()


def get_step_by_run_and_name(db: Session, run_id: int, step_name: str) -> Step | None:
    return (
        db.query(Step)
        .filter(Step.run_id == run_id, Step.step_name == step_name)
        .first()
    )


def mark_step_running(db: Session, step: Step, input_json: dict) -> Step:
    step.status = "running"
    step.finished_at = None
    persist_step_input(db, step, input_json)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def update_step_progress(db: Session, step: Step, output_json: dict) -> Step:
    """Persist partial output while status stays running (multi-round setup)."""
    persist_step_output(db, step, output_json)
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def mark_step_completed(
    db: Session,
    step: Step,
    output_json: dict,
    *,
    commit: bool = True,
) -> Step:
    step.status = "completed"
    persist_step_output(db, step, output_json)
    step.error_text = None
    step.finished_at = datetime.utcnow()
    db.add(step)
    if commit:
        db.commit()
        db.refresh(step)
    else:
        db.flush()
        db.refresh(step)
    return step


def mark_step_failed(db: Session, step: Step, error_text: str) -> Step:
    step.status = "failed"
    step.error_text = error_text
    step.finished_at = datetime.utcnow()
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def increment_step_retry(db: Session, step: Step) -> Step:
    step.retry_count += 1
    step.status = "pending"
    step.error_text = None
    step.finished_at = None
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def reset_stale_running_steps(db: Session) -> int:
    """Fail steps stuck in 'running' from a process that never reached its except block (crash
    between mark_step_running and mark_step_failed/mark_step_completed — deploy, OOM, proxy
    timeout). run_workflow runs synchronously inside the HTTP request, so nothing else will ever
    move such a step out of 'running'. Returns how many were reset.
    """
    stale = db.query(Step).filter(Step.status == "running").all()
    for step in stale:
        step.status = "failed"
        step.error_text = "прервано рестартом процесса (recovery при старте)"
        step.finished_at = datetime.utcnow()
        db.add(step)
    if stale:
        db.commit()
    return len(stale)
