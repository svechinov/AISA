from datetime import datetime

from pydantic import BaseModel


class ResearchTaskRead(BaseModel):
    id: int
    run_id: int
    contact_id: int | None
    company: str | None
    task_type: str
    status: str
    reason: str | None
    input_json: dict
    output_json: dict
    created_at: datetime
    finished_at: datetime | None

    class Config:
        from_attributes = True
