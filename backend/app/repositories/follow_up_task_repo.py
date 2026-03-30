from datetime import datetime

from sqlalchemy.orm import Session

from app.models.follow_up_task import FollowUpTask


def create_follow_up_task(
    db: Session,
    run_id: int,
    thread_id: int,
    contact_id: int,
    task_type: str,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    due_at=None,
    status: str = "open",
    source_json: dict | None = None,
    output_json: dict | None = None,
) -> FollowUpTask:
    task = FollowUpTask(
        run_id=run_id,
        thread_id=thread_id,
        contact_id=contact_id,
        task_type=task_type,
        title=title,
        description=description,
        priority=priority,
        due_at=due_at,
        status=status,
        source_json=source_json or {},
        output_json=output_json or {},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_follow_up_task(db: Session, task_id: int) -> FollowUpTask | None:
    return db.query(FollowUpTask).filter(FollowUpTask.id == task_id).first()


def list_follow_up_tasks_by_run(db: Session, run_id: int) -> list[FollowUpTask]:
    return (
        db.query(FollowUpTask)
        .filter(FollowUpTask.run_id == run_id)
        .order_by(FollowUpTask.id.desc())
        .all()
    )


def list_follow_up_tasks_by_thread(db: Session, thread_id: int) -> list[FollowUpTask]:
    return (
        db.query(FollowUpTask)
        .filter(FollowUpTask.thread_id == thread_id)
        .order_by(FollowUpTask.id.desc())
        .all()
    )


def find_open_follow_up_task_by_thread_and_type(
    db: Session,
    thread_id: int,
    task_type: str,
) -> FollowUpTask | None:
    return (
        db.query(FollowUpTask)
        .filter(
            FollowUpTask.thread_id == thread_id,
            FollowUpTask.task_type == task_type,
            FollowUpTask.status.in_(["open", "in_progress"]),
        )
        .order_by(FollowUpTask.id.desc())
        .first()
    )


def update_follow_up_task_status(
    db: Session,
    task: FollowUpTask,
    status: str,
    output_json: dict | None = None,
) -> FollowUpTask:
    task.status = status
    if output_json is not None:
        task.output_json = output_json

    if status == "completed":
        task.completed_at = datetime.utcnow()

    db.add(task)
    db.commit()
    db.refresh(task)
    return task
