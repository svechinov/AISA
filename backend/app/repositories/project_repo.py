from sqlalchemy.orm import Session

from app.models.project import Project


def create_project(db: Session, name: str, type: str) -> Project:
    project = Project(name=name, type=type)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session, *, archived_only: bool = False) -> list[Project]:
    q = db.query(Project)
    if archived_only:
        q = q.filter(Project.is_archived.is_(True))
    else:
        q = q.filter(Project.is_archived.is_(False))
    return q.order_by(Project.id.desc()).all()


def get_project(db: Session, project_id: int) -> Project | None:
    return db.query(Project).filter(Project.id == project_id).first()


def archive_project(db: Session, project: Project) -> Project:
    project.is_archived = True
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def restore_project(db: Session, project: Project) -> Project:
    project.is_archived = False
    db.add(project)
    db.commit()
    db.refresh(project)
    return project
