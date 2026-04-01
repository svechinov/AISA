from datetime import datetime

from sqlalchemy.orm import Session

from app.models.email_thread import EmailThread


def find_email_thread_by_run_contact_gmail(
    db: Session,
    run_id: int,
    contact_id: int,
    provider_thread_id: str,
) -> EmailThread | None:
    if not provider_thread_id:
        return None
    return (
        db.query(EmailThread)
        .filter(
            EmailThread.run_id == run_id,
            EmailThread.contact_id == contact_id,
            EmailThread.provider_thread_id == provider_thread_id,
        )
        .first()
    )


def create_email_thread(
    db: Session,
    run_id: int,
    contact_id: int,
    draft_id: int | None,
    subject: str,
    provider_thread_id: str | None = None,
    status: str = "open",
    *,
    last_message_at: datetime | None = None,
) -> EmailThread:
    thread = EmailThread(
        run_id=run_id,
        contact_id=contact_id,
        draft_id=draft_id,
        subject=subject,
        provider_thread_id=provider_thread_id,
        status=status,
        last_message_at=last_message_at or datetime.utcnow(),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def get_email_thread(db: Session, thread_id: int) -> EmailThread | None:
    return db.query(EmailThread).filter(EmailThread.id == thread_id).first()


def get_email_thread_by_draft_id(db: Session, draft_id: int) -> EmailThread | None:
    return (
        db.query(EmailThread)
        .filter(EmailThread.draft_id == draft_id)
        .order_by(EmailThread.id.desc())
        .first()
    )


def find_email_thread_by_provider_thread_id(db: Session, provider_thread_id: str) -> EmailThread | None:
    return (
        db.query(EmailThread)
        .filter(EmailThread.provider_thread_id == provider_thread_id)
        .first()
    )


def list_email_threads_by_run(db: Session, run_id: int) -> list[EmailThread]:
    return (
        db.query(EmailThread)
        .filter(EmailThread.run_id == run_id)
        .order_by(EmailThread.id.desc())
        .all()
    )


def update_email_thread_status(db: Session, thread: EmailThread, status: str) -> EmailThread:
    thread.status = status
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def touch_email_thread(db: Session, thread: EmailThread) -> EmailThread:
    thread.last_message_at = datetime.utcnow()
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def bump_email_thread_last_message_at(db: Session, thread: EmailThread, at: datetime) -> EmailThread:
    cur = thread.last_message_at
    if cur is None or at > cur:
        thread.last_message_at = at
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread
