from sqlalchemy.orm import Session

from app.models.email_message import EmailMessage


def get_email_message_by_provider_id(db: Session, provider_message_id: str) -> EmailMessage | None:
    if not provider_message_id:
        return None
    return (
        db.query(EmailMessage)
        .filter(EmailMessage.provider_message_id == provider_message_id)
        .first()
    )


def create_email_message(
    db: Session,
    thread_id: int,
    run_id: int,
    contact_id: int,
    draft_id: int | None,
    direction: str,
    from_email: str | None,
    to_email: str | None,
    subject: str,
    body: str,
    provider_message_id: str | None = None,
) -> EmailMessage:
    message = EmailMessage(
        thread_id=thread_id,
        run_id=run_id,
        contact_id=contact_id,
        draft_id=draft_id,
        direction=direction,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=body,
        provider_message_id=provider_message_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_email_messages_by_thread(db: Session, thread_id: int) -> list[EmailMessage]:
    return (
        db.query(EmailMessage)
        .filter(EmailMessage.thread_id == thread_id)
        .order_by(EmailMessage.id.asc())
        .all()
    )


def list_email_messages_by_run(db: Session, run_id: int) -> list[EmailMessage]:
    return (
        db.query(EmailMessage)
        .filter(EmailMessage.run_id == run_id)
        .order_by(EmailMessage.id.asc())
        .all()
    )
