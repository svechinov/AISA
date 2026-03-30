from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.follow_up_task_repo import (
    get_follow_up_task,
    list_follow_up_tasks_by_run,
    list_follow_up_tasks_by_thread,
    update_follow_up_task_status as repo_update_follow_up_task_status,
)
from app.schemas.follow_up_task import FollowUpTaskRead, FollowUpTaskStatusUpdate
from app.services.follow_up_service import create_next_action_for_thread

router = APIRouter(prefix="/follow-up-tasks", tags=["follow-up-tasks"])


@router.get("/run/{run_id}", response_model=list[FollowUpTaskRead])
def list_follow_up_tasks_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_follow_up_tasks_by_run(db, run_id)


@router.get("/thread/{thread_id}", response_model=list[FollowUpTaskRead])
def list_follow_up_tasks_for_thread(thread_id: int, db: Session = Depends(get_db)):
    return list_follow_up_tasks_by_thread(db, thread_id)


@router.post("/thread/{thread_id}/create-next-action")
def create_next_action_route(thread_id: int, db: Session = Depends(get_db)):
    try:
        return create_next_action_for_thread(db, thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{task_id}/status", response_model=FollowUpTaskRead)
def update_follow_up_task_status_route(
    task_id: int,
    payload: FollowUpTaskStatusUpdate,
    db: Session = Depends(get_db),
):
    task = get_follow_up_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Follow-up task not found")

    if payload.status not in {"open", "in_progress", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid follow-up task status")

    return repo_update_follow_up_task_status(
        db=db,
        task=task,
        status=payload.status,
        output_json=payload.output_json,
    )
