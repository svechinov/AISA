from sqlalchemy.orm import Session

from app.models.email_event import EmailEvent


def create_email_event(
    db: Session,
    run_id: int,
    draft_id: int,
    contact_id: int,
    event_type: str,
    provider_message_id: str | None = None,
    payload_json: dict | None = None,
    error_message: str | None = None,
) -> EmailEvent:
    event = EmailEvent(
        run_id=run_id,
        draft_id=draft_id,
        contact_id=contact_id,
        event_type=event_type,
        provider_message_id=provider_message_id,
        payload_json=payload_json or {},
        error_message=error_message,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_email_events_by_run(db: Session, run_id: int) -> list[EmailEvent]:
    return (
        db.query(EmailEvent)
        .filter(EmailEvent.run_id == run_id)
        .order_by(EmailEvent.id.asc())
        .all()
    )


def list_email_events_by_draft(db: Session, draft_id: int) -> list[EmailEvent]:
    return (
        db.query(EmailEvent)
        .filter(EmailEvent.draft_id == draft_id)
        .order_by(EmailEvent.id.asc())
        .all()
    )
