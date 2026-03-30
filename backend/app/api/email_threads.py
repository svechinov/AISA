from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_message_repo import list_email_messages_by_run, list_email_messages_by_thread
from app.repositories.email_thread_repo import get_email_thread, list_email_threads_by_run
from app.schemas.email_message import EmailMessageRead
from app.schemas.email_thread import EmailThreadRead

router = APIRouter(prefix="/email-threads", tags=["email-threads"])


@router.get("/run/{run_id}/messages", response_model=list[EmailMessageRead])
def list_messages_for_run_route(run_id: int, db: Session = Depends(get_db)):
    return list_email_messages_by_run(db, run_id)


@router.get("/run/{run_id}", response_model=list[EmailThreadRead])
def list_threads_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_email_threads_by_run(db, run_id)


@router.get("/{thread_id}/messages", response_model=list[EmailMessageRead])
def list_thread_messages_route(thread_id: int, db: Session = Depends(get_db)):
    return list_email_messages_by_thread(db, thread_id)


@router.get("/{thread_id}", response_model=EmailThreadRead)
def get_thread_route(thread_id: int, db: Session = Depends(get_db)):
    t = get_email_thread(db, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    return t
