from sqlalchemy.orm import Session

from app.repositories.rule_repo import (
    list_active_global_rules,
    list_active_project_rules,
    list_active_step_rules,
    list_active_workflow_rules,
)
from app.repositories.run_repo import get_run


def get_effective_rules(
    db: Session,
    project_id: int,
    workflow_name: str,
    step_name: str,
) -> list[str]:
    rules: list[str] = []

    rules.extend([r.content for r in list_active_global_rules(db)])
    rules.extend([r.content for r in list_active_project_rules(db, project_id)])
    rules.extend([r.content for r in list_active_workflow_rules(db, workflow_name)])
    rules.extend([r.content for r in list_active_step_rules(db, workflow_name, step_name)])

    return rules


def get_effective_rules_from_run(
    db: Session,
    run_id: int,
    step_name: str,
) -> list[str]:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    return get_effective_rules(
        db=db,
        project_id=run.project_id,
        workflow_name=run.workflow_name,
        step_name=step_name,
    )
