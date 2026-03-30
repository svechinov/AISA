from datetime import datetime

from pydantic import BaseModel


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


class FollowUpTaskStatusUpdate(BaseModel):
    status: str
    output_json: dict | None = None
