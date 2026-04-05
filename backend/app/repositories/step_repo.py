from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.step import Step


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


def get_find_contacts_for_matching(db: Session, run_id: int) -> tuple[list[dict], str]:
    """
    Contacts as name/website/email only.

    On PostgreSQL we aggregate tiny json objects in SQL so we never deserialize the full
    find_contacts output_json blob (can be huge per contact). Else ORM + shrink after full load.
    """
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        row = db.execute(
            text(
                """
                SELECT COALESCE(
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'name', elem->'name',
                                'website', elem->'website',
                                'email', elem->'email'
                            )
                        )
                        FROM jsonb_array_elements(
                            CASE
                                WHEN s.output_json IS NULL THEN '[]'::jsonb
                                WHEN jsonb_typeof((s.output_json::jsonb)->'contacts') = 'array'
                                THEN (s.output_json::jsonb)->'contacts'
                                ELSE '[]'::jsonb
                            END
                        ) AS elem
                    ),
                    '[]'::jsonb
                )
                FROM steps s
                WHERE s.run_id = :run_id AND s.step_name = 'find_contacts'
                LIMIT 1
                """
            ),
            {"run_id": run_id},
        ).scalar_one_or_none()
        if row is None:
            return [], "postgres_min_json"
        if isinstance(row, list):
            out = [x for x in row if isinstance(x, dict)]
            return [_contact_lite_dict(x) for x in out], "postgres_min_json"
        return [], "postgres_min_json"

    step = get_step_by_run_and_name(db, run_id, "find_contacts")
    if not step:
        return [], "orm_full"
    raw = (step.output_json or {}).get("contacts")
    if not isinstance(raw, list):
        return [], "orm_full"
    return [_contact_lite_dict(ct) for ct in raw if isinstance(ct, dict)], "orm_full"


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
        input_json=input_json,
        output_json={},
    )
    db.add(step)
    if commit:
        db.commit()
        db.refresh(step)
    else:
        db.flush()
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
    step.input_json = input_json
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def update_step_progress(db: Session, step: Step, output_json: dict) -> Step:
    """Persist partial output while status stays running (multi-round setup)."""
    step.output_json = output_json
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
    step.output_json = output_json
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
