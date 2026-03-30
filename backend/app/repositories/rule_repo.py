from sqlalchemy.orm import Session

from app.models.rule import Rule


def list_active_global_rules(db: Session) -> list[Rule]:
    return (
        db.query(Rule)
        .filter(Rule.scope == "global", Rule.active.is_(True))
        .order_by(Rule.id.asc())
        .all()
    )


def list_active_project_rules(db: Session, project_id: int) -> list[Rule]:
    return (
        db.query(Rule)
        .filter(
            Rule.scope == "project",
            Rule.project_id == project_id,
            Rule.active.is_(True),
        )
        .order_by(Rule.id.asc())
        .all()
    )


def list_active_workflow_rules(db: Session, workflow_name: str) -> list[Rule]:
    return (
        db.query(Rule)
        .filter(
            Rule.scope == "workflow",
            Rule.workflow_name == workflow_name,
            Rule.active.is_(True),
        )
        .order_by(Rule.id.asc())
        .all()
    )


def list_active_step_rules(db: Session, workflow_name: str, step_name: str) -> list[Rule]:
    return (
        db.query(Rule)
        .filter(
            Rule.scope == "step",
            Rule.workflow_name == workflow_name,
            Rule.step_name == step_name,
            Rule.active.is_(True),
        )
        .order_by(Rule.id.asc())
        .all()
    )


def create_rule(
    db: Session,
    scope: str,
    content: str,
    project_id: int | None = None,
    workflow_name: str | None = None,
    step_name: str | None = None,
    active: bool = True,
) -> Rule:
    rule = Rule(
        scope=scope,
        content=content,
        project_id=project_id,
        workflow_name=workflow_name,
        step_name=step_name,
        active=active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
