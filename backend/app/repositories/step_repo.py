from datetime import datetime

from sqlalchemy.orm import Session

from app.models.step import Step


def create_step(db: Session, run_id: int, step_name: str, input_json: dict) -> Step:
    step = Step(
        run_id=run_id,
        step_name=step_name,
        status="pending",
        input_json=input_json,
        output_json={},
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def list_steps_by_run(db: Session, run_id: int) -> list[Step]:
    return (
        db.query(Step)
        .filter(Step.run_id == run_id)
        .order_by(Step.id.asc())
        .all()
    )


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


def mark_step_completed(db: Session, step: Step, output_json: dict) -> Step:
    step.status = "completed"
    step.output_json = output_json
    step.error_text = None
    step.finished_at = datetime.utcnow()
    db.add(step)
    db.commit()
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
