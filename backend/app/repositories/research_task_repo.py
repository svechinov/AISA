from datetime import datetime

from sqlalchemy.orm import Session

from app.models.research_task import ResearchTask
from app.utils.research_task_payload import persist_research_input, persist_research_output


def create_research_task(
    db: Session,
    run_id: int,
    task_type: str,
    company: str | None,
    contact_id: int | None = None,
    status: str = "open",
    reason: str | None = None,
    input_json: dict | None = None,
    output_json: dict | None = None,
) -> ResearchTask:
    task = ResearchTask(
        run_id=run_id,
        contact_id=contact_id,
        company=company,
        task_type=task_type,
        status=status,
        reason=reason,
        input_json={},
        output_json={},
    )
    db.add(task)
    db.flush()
    persist_research_input(db, task, input_json or {})
    persist_research_output(db, task, output_json or {})
    db.commit()
    db.refresh(task)
    return task


def get_research_task_by_id(db: Session, task_id: int) -> ResearchTask | None:
    return db.query(ResearchTask).filter(ResearchTask.id == task_id).first()


def mark_research_task_running(db: Session, task: ResearchTask) -> ResearchTask:
    task.status = "running"
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def mark_research_task_completed(db: Session, task: ResearchTask, output_json: dict) -> ResearchTask:
    task.status = "completed"
    persist_research_output(db, task, output_json)
    task.finished_at = datetime.utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def mark_research_task_no_result(db: Session, task: ResearchTask, output_json: dict) -> ResearchTask:
    task.status = "no_result"
    persist_research_output(db, task, output_json)
    task.finished_at = datetime.utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def mark_research_task_failed(db: Session, task: ResearchTask, output_json: dict) -> ResearchTask:
    task.status = "failed"
    persist_research_output(db, task, output_json)
    task.finished_at = datetime.utcnow()
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def find_pending_replacement_task(db: Session, run_id: int, contact_id: int) -> ResearchTask | None:
    """Blocks a second manual/auto task while one is still in progress or needs retry."""
    return (
        db.query(ResearchTask)
        .filter(
            ResearchTask.run_id == run_id,
            ResearchTask.contact_id == contact_id,
            ResearchTask.task_type == "find_replacement_email",
            ResearchTask.status.in_(["open", "running", "failed", "no_result"]),
        )
        .first()
    )


def list_research_tasks_by_run(db: Session, run_id: int) -> list[ResearchTask]:
    return (
        db.query(ResearchTask)
        .filter(ResearchTask.run_id == run_id)
        .order_by(ResearchTask.id.asc())
        .all()
    )
