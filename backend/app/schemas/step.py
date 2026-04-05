from datetime import datetime

from pydantic import BaseModel

from sqlalchemy.orm import Session


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


def step_to_read(db: Session, step) -> StepRead:
    from app.utils.step_payload import effective_step_input_json, effective_step_output_json

    return StepRead(
        id=step.id,
        run_id=step.run_id,
        step_name=step.step_name,
        status=step.status,
        input_json=effective_step_input_json(db, step),
        output_json=effective_step_output_json(db, step),
        error_text=step.error_text,
        retry_count=step.retry_count,
        created_at=step.created_at,
        finished_at=step.finished_at,
    )
