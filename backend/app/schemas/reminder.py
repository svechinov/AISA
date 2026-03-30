from datetime import datetime

from pydantic import BaseModel


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


class ReminderCreateForTask(BaseModel):
    remind_at: datetime | None = None


class ReminderStatusUpdate(BaseModel):
    status: str
    output_json: dict | None = None


class ReminderSnoozeUpdate(BaseModel):
    remind_at: datetime
    output_json: dict | None = None
