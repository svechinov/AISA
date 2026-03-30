from datetime import datetime
from pydantic import BaseModel


class RuleCreate(BaseModel):
    scope: str
    content: str
    project_id: int | None = None
    workflow_name: str | None = None
    step_name: str | None = None
    active: bool = True


class RuleRead(BaseModel):
    id: int
    scope: str
    project_id: int | None
    workflow_name: str | None
    step_name: str | None
    content: str
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True
