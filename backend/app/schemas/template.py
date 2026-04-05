from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.template import Template


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


def build_template_read(db: Session, template: Template) -> TemplateRead:
    """Variables from template_variables (lazy-migrates legacy variables_json on first read)."""
    from app.utils.template_variables_io import effective_variables_json_for_api

    v = effective_variables_json_for_api(db, template.id)
    return TemplateRead(
        id=template.id,
        project_id=template.project_id,
        template_type=template.template_type,
        name=template.name,
        content=template.content,
        variables_json=v,
        created_at=template.created_at,
    )
