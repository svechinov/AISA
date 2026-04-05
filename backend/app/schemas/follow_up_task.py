from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session


class FollowUpTaskRead(BaseModel):
    id: int
    run_id: int
    thread_id: int
    contact_id: int
    task_type: str
    status: str
    priority: str
    title: str
    description: str | None
    due_at: datetime | None
    completed_at: datetime | None
    source_json: dict
    output_json: dict
    created_at: datetime

    class Config:
        from_attributes = True


def follow_up_task_to_read(db: Session, task) -> FollowUpTaskRead:
    from app.utils.follow_up_task_payload import effective_follow_up_output_json, effective_follow_up_source_json

    return FollowUpTaskRead(
        id=task.id,
        run_id=task.run_id,
        thread_id=task.thread_id,
        contact_id=task.contact_id,
        task_type=task.task_type,
        status=task.status,
        priority=task.priority,
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        completed_at=task.completed_at,
        source_json=effective_follow_up_source_json(db, task),
        output_json=effective_follow_up_output_json(db, task),
        created_at=task.created_at,
    )


class FollowUpTaskStatusUpdate(BaseModel):
    status: str
    output_json: dict | None = None
