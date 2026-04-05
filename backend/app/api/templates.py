from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.template_repo import create_template, get_template, list_templates
from app.schemas.template import TemplateCreate, TemplateRead, build_template_read

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=TemplateRead)
def create_template_route(payload: TemplateCreate, db: Session = Depends(get_db)):
    t = create_template(
        db=db,
        project_id=payload.project_id,
        template_type=payload.template_type,
        name=payload.name,
        content=payload.content,
        variables_json=payload.variables_json,
    )
    return build_template_read(db, t)


@router.get("", response_model=list[TemplateRead])
def list_templates_route(
    project_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    rows = list_templates(db, project_id=project_id)
    return [build_template_read(db, t) for t in rows]


@router.get("/{template_id}", response_model=TemplateRead)
def get_template_route(template_id: int, db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return build_template_read(db, template)
