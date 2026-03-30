from datetime import datetime
from pydantic import BaseModel


class StepRead(BaseModel):
    id: int
    run_id: int
    step_name: str
    status: str
    input_json: dict
    output_json: dict
    error_text: str | None
    retry_count: int
    created_at: datetime
    finished_at: datetime | None

    class Config:
        from_attributes = True
