from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.project_repo import (
    archive_project,
    create_project,
    get_project,
    list_projects,
    restore_project,
)
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead)
def create_project_route(payload: ProjectCreate, db: Session = Depends(get_db)):
    return create_project(db, name=payload.name, type=payload.type)


@router.get("", response_model=list[ProjectRead])
def list_projects_route(
    archived: bool = Query(False, description="If true, list archived projects only"),
    db: Session = Depends(get_db),
):
    return list_projects(db, archived_only=archived)


def _archive_existing_project(db: Session, project_id: int) -> ProjectRead:
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return archive_project(db, project)


@router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project_post_route(project_id: int, db: Session = Depends(get_db)):
    """Prefer this over DELETE: same semantics, fewer proxy/method issues."""
    return _archive_existing_project(db, project_id)


@router.delete("/{project_id}", response_model=ProjectRead)
def archive_project_route(project_id: int, db: Session = Depends(get_db)):
    return _archive_existing_project(db, project_id)


@router.post("/{project_id}/restore", response_model=ProjectRead)
def restore_project_route(project_id: int, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return restore_project(db, project)
