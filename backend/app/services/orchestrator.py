from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run, update_run_status
from app.repositories.step_repo import (
    create_step,
    get_step_by_run_and_name,
    mark_step_completed,
    mark_step_failed,
    mark_step_running,
)
from app.services.contact_persistence_service import persist_validated_contacts
from app.services.email_draft_persistence_service import persist_generated_emails
from app.services.run_context_service import build_pack_step_zero_input
from app.services.workflow_registry import WORKFLOWS
from app.workers.contacts_worker import find_contacts, validate_contacts
from app.workers.email_worker import generate_emails, generate_master_email_draft
from app.workers.research_worker import collect_companies


STEP_HANDLERS = {
    "collect_companies": collect_companies,
    "find_contacts": find_contacts,
    "validate_contacts": validate_contacts,
    "generate_master_email_draft": generate_master_email_draft,
    "generate_emails": generate_emails,
}


def get_workflow_steps(workflow_name: str) -> list[str]:
    if workflow_name not in WORKFLOWS:
        raise ValueError(f"Unknown workflow: {workflow_name}")
    return WORKFLOWS[workflow_name]


def build_step_input(db: Session, run_id: int, step_name: str) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    workflow_steps = get_workflow_steps(run.workflow_name)
    step_index = workflow_steps.index(step_name)

    if step_index == 0:
        return build_pack_step_zero_input(run)

    previous_step_name = workflow_steps[step_index - 1]
    previous_step = get_step_by_run_and_name(db, run_id, previous_step_name)

    if not previous_step:
        raise ValueError(f"Previous step {previous_step_name} not found")

    return previous_step.output_json or {}


def execute_step(db: Session, run_id: int, step_name: str):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    step = get_step_by_run_and_name(db, run_id, step_name)
    if not step:
        step = create_step(db, run_id, step_name, {})

    step_input = build_step_input(db, run_id, step_name)
    mark_step_running(db, step, step_input)

    handler = STEP_HANDLERS[step_name]

    try:
        output = handler(
            db=db,
            run_id=run_id,
            workflow_name=run.workflow_name,
            step_input=step_input,
        )
        mark_step_completed(db, step, output)

        if step_name == "validate_contacts":
            persist_validated_contacts(db, run_id, output)

        if step_name == "generate_emails":
            persist_generated_emails(db, run_id, output)

    except Exception as e:
        mark_step_failed(db, step, str(e))
        raise


def run_workflow(db: Session, run_id: int):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    update_run_status(db, run, "running")

    try:
        for step_name in get_workflow_steps(run.workflow_name):
            execute_step(db, run_id, step_name)

            if step_name == "validate_contacts":
                run = get_run(db, run_id)
                update_run_status(db, run, "needs_review")
                return

        run = get_run(db, run_id)
        update_run_status(db, run, "completed")
    except Exception:
        run = get_run(db, run_id)
        update_run_status(db, run, "failed")
        raise


def continue_workflow_after_review(db: Session, run_id: int):
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    if run.status != "needs_review":
        raise ValueError(f"Run {run_id} is not waiting for review")

    update_run_status(db, run, "running")

    try:
        execute_step(db, run_id, "generate_master_email_draft")
        execute_step(db, run_id, "generate_emails")
        run = get_run(db, run_id)
        update_run_status(db, run, "drafts_ready")
    except Exception:
        run = get_run(db, run_id)
        update_run_status(db, run, "failed")
        raise
