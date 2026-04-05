from datetime import datetime

from pydantic import BaseModel

from app.models.reminder import Reminder


class ReminderRead(BaseModel):
    id: int
    run_id: int
    follow_up_task_id: int | None
    thread_id: int | None
    contact_id: int | None
    title: str
    description: str | None
    remind_at: datetime
    status: str
    priority: str
    source_json: dict
    output_json: dict
    triggered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


def reminder_to_read(r: Reminder) -> ReminderRead:
    from app.utils.reminder_payload import effective_output_json, effective_source_json

    return ReminderRead(
        id=r.id,
        run_id=r.run_id,
        follow_up_task_id=r.follow_up_task_id,
        thread_id=r.thread_id,
        contact_id=r.contact_id,
        title=r.title,
        description=r.description,
        remind_at=r.remind_at,
        status=r.status,
        priority=r.priority,
        source_json=effective_source_json(r),
        output_json=effective_output_json(r),
        triggered_at=r.triggered_at,
        completed_at=r.completed_at,
        created_at=r.created_at,
    )


class ReminderCreateForTask(BaseModel):
    remind_at: datetime | None = None


class ReminderCreateForThread(BaseModel):
    """When omitted, backend defaults to a few days ahead (UTC)."""

    remind_at: datetime | None = None


class ReminderStatusUpdate(BaseModel):
    status: str
    output_json: dict | None = None


class ReminderSnoozeUpdate(BaseModel):
    remind_at: datetime
    output_json: dict | None = None
