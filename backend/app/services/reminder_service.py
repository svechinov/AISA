from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories.follow_up_task_repo import get_follow_up_task
from app.repositories.reminder_repo import (
    create_reminder,
    find_active_reminder_for_follow_up_task,
)


def create_reminder_for_follow_up_task(
    db: Session,
    follow_up_task_id: int,
    remind_at=None,
) -> dict:
    task = get_follow_up_task(db, follow_up_task_id)
    if not task:
        raise ValueError(f"Follow-up task {follow_up_task_id} not found")

    existing = find_active_reminder_for_follow_up_task(db, task.id)
    if existing:
        return {
            "follow_up_task_id": task.id,
            "reminder_id": existing.id,
            "deduplicated": True,
        }

    effective_remind_at = remind_at or task.due_at or (datetime.utcnow() + timedelta(days=7))

    reminder = create_reminder(
        db=db,
        run_id=task.run_id,
        follow_up_task_id=task.id,
        thread_id=task.thread_id,
        contact_id=task.contact_id,
        title=task.title,
        description=task.description,
        remind_at=effective_remind_at,
        status="scheduled",
        priority=task.priority,
        source_json={
            "source": "follow_up_task",
            "follow_up_task_id": task.id,
            "task_type": task.task_type,
        },
        output_json={},
    )

    return {
        "follow_up_task_id": task.id,
        "reminder_id": reminder.id,
        "deduplicated": False,
    }
