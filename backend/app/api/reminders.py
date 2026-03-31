from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.reminder_repo import (
    get_reminder,
    list_reminders_by_follow_up_task,
    list_reminders_by_run,
    snooze_reminder,
    update_reminder_status,
)
from app.schemas.reminder import (
    ReminderCreateForTask,
    ReminderCreateForThread,
    ReminderRead,
    ReminderSnoozeUpdate,
    ReminderStatusUpdate,
)
from app.services.reminder_scheduler import trigger_due_reminders
from app.services.reminder_service import create_reminder_for_follow_up_task
from app.services.reminder_thread_service import create_reminder_for_thread

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/run/{run_id}", response_model=list[ReminderRead])
def list_reminders_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_reminders_by_run(db, run_id)


@router.get("/follow-up-task/{follow_up_task_id}", response_model=list[ReminderRead])
def list_reminders_for_follow_up_task(follow_up_task_id: int, db: Session = Depends(get_db)):
    return list_reminders_by_follow_up_task(db, follow_up_task_id)


@router.post("/follow-up-task/{follow_up_task_id}/create")
def create_reminder_for_task_route(
    follow_up_task_id: int,
    payload: ReminderCreateForTask,
    db: Session = Depends(get_db),
):
    try:
        return create_reminder_for_follow_up_task(
            db=db,
            follow_up_task_id=follow_up_task_id,
            remind_at=payload.remind_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/thread/{thread_id}/create")
def create_reminder_for_thread_route(
    thread_id: int,
    payload: ReminderCreateForThread,
    db: Session = Depends(get_db),
):
    try:
        return create_reminder_for_thread(
            db=db,
            thread_id=thread_id,
            remind_at=payload.remind_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{reminder_id}/status", response_model=ReminderRead)
def update_reminder_status_route(
    reminder_id: int,
    payload: ReminderStatusUpdate,
    db: Session = Depends(get_db),
):
    reminder = get_reminder(db, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    if payload.status not in {"scheduled", "triggered", "completed", "cancelled", "snoozed"}:
        raise HTTPException(status_code=400, detail="Invalid reminder status")

    return update_reminder_status(
        db=db,
        reminder=reminder,
        status=payload.status,
        output_json=payload.output_json,
    )


@router.patch("/{reminder_id}/snooze", response_model=ReminderRead)
def snooze_reminder_route(
    reminder_id: int,
    payload: ReminderSnoozeUpdate,
    db: Session = Depends(get_db),
):
    reminder = get_reminder(db, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")

    return snooze_reminder(
        db=db,
        reminder=reminder,
        remind_at=payload.remind_at,
        output_json=payload.output_json,
    )


@router.post("/trigger-due")
def trigger_due_reminders_route(db: Session = Depends(get_db)):
    return trigger_due_reminders(db)
