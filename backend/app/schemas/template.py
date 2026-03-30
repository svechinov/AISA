from datetime import datetime

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    project_id: int | None = None
    template_type: str
    name: str
    content: str
    variables_json: dict = Field(default_factory=dict)


class TemplateRead(BaseModel):
    id: int
    project_id: int | None
    template_type: str
    name: str
    content: str
    variables_json: dict
    created_at: datetime

    class Config:
        from_attributes = True
