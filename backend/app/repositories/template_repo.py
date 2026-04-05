from sqlalchemy.orm import Session

from app.models.template import Template
from app.utils.template_variables_io import replace_template_variables_from_dict


def create_template(
    db: Session,
    template_type: str,
    name: str,
    content: str,
    variables_json: dict,
    project_id: int | None = None,
) -> Template:
    template = Template(
        project_id=project_id,
        template_type=template_type,
        name=name,
        content=content,
        variables_json={},
    )
    db.add(template)
    db.flush()
    replace_template_variables_from_dict(db, template.id, variables_json)
    db.commit()
    db.refresh(template)
    return template


def list_templates(db: Session, project_id: int | None = None) -> list[Template]:
    query = db.query(Template)

    if project_id is None:
        query = query.filter(Template.project_id.is_(None))
    else:
        query = query.filter(
            (Template.project_id == project_id) | (Template.project_id.is_(None))
        )

    return query.order_by(Template.id.asc()).all()


def get_template(db: Session, template_id: int) -> Template | None:
    return db.query(Template).filter(Template.id == template_id).first()


def get_template_by_type(
    db: Session,
    template_type: str,
    project_id: int | None = None,
) -> Template | None:
    query = db.query(Template).filter(Template.template_type == template_type)

    if project_id is None:
        query = query.filter(Template.project_id.is_(None))
        return query.order_by(Template.id.desc()).first()

    project_template = (
        query.filter(Template.project_id == project_id)
        .order_by(Template.id.desc())
        .first()
    )
    if project_template:
        return project_template

    return (
        db.query(Template)
        .filter(
            Template.template_type == template_type,
            Template.project_id.is_(None),
        )
        .order_by(Template.id.desc())
        .first()
    )
