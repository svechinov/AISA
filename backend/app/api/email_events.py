from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_event_repo import list_email_events_by_draft, list_email_events_by_run
from app.schemas.email_event import EmailEventRead, email_event_to_read

router = APIRouter(prefix="/email-events", tags=["email-events"])


@router.get("/run/{run_id}", response_model=list[EmailEventRead])
def list_events_for_run(run_id: int, db: Session = Depends(get_db)):
    return [email_event_to_read(e) for e in list_email_events_by_run(db, run_id)]


@router.get("/draft/{draft_id}", response_model=list[EmailEventRead])
def list_events_for_draft(draft_id: int, db: Session = Depends(get_db)):
    return [email_event_to_read(e) for e in list_email_events_by_draft(db, draft_id)]
