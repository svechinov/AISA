"""Send-volume metrics derived from email_events (the single source of truth for caps).

We count event_type='sent' rows rather than a separate counter, so caps can never drift from
what was actually sent. Single mailbox today: send_from_email is NULL on Gmail sends, so we count
rows matching the mailbox OR with a NULL sender (legacy/Gmail). Multi-mailbox later tightens this."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.email_event import EmailEvent


def _mailbox_filter(mailbox: str | None):
    if not mailbox:
        return None
    m = mailbox.strip().lower()
    return or_(EmailEvent.send_from_email == m, EmailEvent.send_from_email.is_(None))


def count_sent_since(db: Session, since_utc: datetime, mailbox: str | None = None) -> int:
    q = db.query(EmailEvent.id).filter(
        EmailEvent.event_type == "sent",
        EmailEvent.created_at >= since_utc,
    )
    mf = _mailbox_filter(mailbox)
    if mf is not None:
        q = q.filter(mf)
    return q.count()


def last_sent_at(db: Session, mailbox: str | None = None) -> datetime | None:
    q = db.query(EmailEvent.created_at).filter(EmailEvent.event_type == "sent")
    mf = _mailbox_filter(mailbox)
    if mf is not None:
        q = q.filter(mf)
    row = q.order_by(EmailEvent.created_at.desc()).first()
    return row[0] if row else None
