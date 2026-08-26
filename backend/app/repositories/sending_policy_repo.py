from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.sending_policy import SendingPolicy


def get_policy_for_mailbox(db: Session, mailbox_email: str) -> SendingPolicy | None:
    m = (mailbox_email or "").strip().lower()
    if not m:
        return None
    return db.query(SendingPolicy).filter(SendingPolicy.mailbox_email == m).first()


def get_default_policy(db: Session) -> SendingPolicy | None:
    """The single enabled mailbox policy (MVP). First enabled row by id when several exist."""
    return (
        db.query(SendingPolicy)
        .filter(SendingPolicy.enabled.is_(True))
        .order_by(SendingPolicy.id.asc())
        .first()
    )


def get_policy_by_id(db: Session, policy_id: int) -> SendingPolicy | None:
    return db.query(SendingPolicy).filter(SendingPolicy.id == policy_id).first()


def list_sending_policies(db: Session) -> list[SendingPolicy]:
    return db.query(SendingPolicy).order_by(SendingPolicy.id.asc()).all()
