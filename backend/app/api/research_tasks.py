from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.contact_repo import find_replacement_contact_for_source, get_contact
from app.repositories.research_task_repo import (
    create_research_task,
    find_pending_replacement_task,
    get_research_task_by_id,
    list_research_tasks_by_run,
)
from app.schemas.research_task import ResearchTaskRead, research_task_to_read
from app.services.research_task_input import build_find_replacement_input_json
from app.services.research_task_runner import run_replacement_task

router = APIRouter(prefix="/research-tasks", tags=["research-tasks"])


class FindReplacementBody(BaseModel):
    contact_id: int


class ReplacementRerunResponse(BaseModel):
    run: dict
    task: ResearchTaskRead


@router.get("/run/{run_id}", response_model=list[ResearchTaskRead])
def list_research_tasks_for_run(run_id: int, db: Session = Depends(get_db)):
    return [research_task_to_read(db, t) for t in list_research_tasks_by_run(db, run_id)]


@router.post("/run/{run_id}/find-replacement", response_model=ResearchTaskRead)
def create_find_replacement_for_contact(
    run_id: int,
    body: FindReplacementBody,
    db: Session = Depends(get_db),
):
    contact = get_contact(db, body.contact_id)
    if not contact or contact.run_id != run_id:
        raise HTTPException(status_code=404, detail="Contact not found for this run")

    existing = find_pending_replacement_task(db, run_id, body.contact_id)
    if existing:
        return existing

    if find_replacement_contact_for_source(db, run_id, body.contact_id):
        raise HTTPException(
            status_code=400,
            detail="Replacement contact already exists for this source",
        )

    reason = f"email_health={contact.email_health}"
    input_json = build_find_replacement_input_json(contact)
    task = create_research_task(
        db,
        run_id=run_id,
        task_type="find_replacement_email",
        company=contact.company,
        contact_id=contact.id,
        status="open",
        reason=reason,
        input_json=input_json,
    )
    return research_task_to_read(db, task)


@router.post("/{task_id}/rerun", response_model=ReplacementRerunResponse)
def rerun_research_task_route(task_id: int, db: Session = Depends(get_db)):
    task = get_research_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Research task not found")

    try:
        run_payload = run_replacement_task(db, task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    task = get_research_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=500, detail="Task disappeared after run")

    return ReplacementRerunResponse(run=run_payload, task=research_task_to_read(db, task))
