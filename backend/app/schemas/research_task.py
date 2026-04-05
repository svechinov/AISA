from datetime import datetime

from pydantic import BaseModel
from sqlalchemy.orm import Session


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


def research_task_to_read(db: Session, task) -> ResearchTaskRead:
    from app.utils.research_task_payload import effective_research_input_json, effective_research_output_json

    return ResearchTaskRead(
        id=task.id,
        run_id=task.run_id,
        contact_id=task.contact_id,
        company=task.company,
        task_type=task.task_type,
        status=task.status,
        reason=task.reason,
        input_json=effective_research_input_json(db, task),
        output_json=effective_research_output_json(db, task),
        created_at=task.created_at,
        finished_at=task.finished_at,
    )
