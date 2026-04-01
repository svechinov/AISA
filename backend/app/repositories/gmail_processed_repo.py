from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.gmail_processed_message import GmailProcessedMessage


def gmail_notification_already_processed(db: Session, provider_message_id: str, kind: str) -> bool:
    pid = (provider_message_id or "").strip()
    if not pid:
        return True
    q = (
        db.query(GmailProcessedMessage.id)
        .filter(
            GmailProcessedMessage.provider_message_id == pid,
            GmailProcessedMessage.kind == kind,
        )
        .first()
    )
    return q is not None


def record_gmail_notification_processed(db: Session, provider_message_id: str, kind: str) -> None:
    pid = (provider_message_id or "").strip()
    if not pid:
        return
    row = GmailProcessedMessage(provider_message_id=pid, kind=kind)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
