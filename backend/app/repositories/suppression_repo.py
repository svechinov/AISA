from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.suppression_entry import REASON_MANUAL, SuppressionEntry
from app.utils.email_normalize import normalize_email as _norm


def is_suppressed(db: Session, email: str | None) -> bool:
    e = _norm(email)
    if not e:
        return False
    return (
        db.query(SuppressionEntry.id)
        .filter(SuppressionEntry.email == e)
        .filter(or_(SuppressionEntry.expires_at.is_(None), SuppressionEntry.expires_at > datetime.utcnow()))
        .first()
        is not None
    )


def get_suppression(db: Session, email: str | None) -> SuppressionEntry | None:
    e = _norm(email)
    if not e:
        return None
    return db.query(SuppressionEntry).filter(SuppressionEntry.email == e).first()


def add_suppression(
    db: Session,
    email: str | None,
    reason: str = REASON_MANUAL,
    source_run_id: int | None = None,
    note: str | None = None,
    expires_at: datetime | None = None,
) -> SuppressionEntry | None:
    """Idempotent upsert by email. Returns the row (existing or new); None if email is blank.

    expires_at=None (default) is permanent — unsubscribe/dead_mailbox/bounced/manual keep their
    existing forever semantics. A datetime is a cooldown (not_interested, B-138): is_suppressed()
    ignores the row once expires_at is in the past.
    """
    e = _norm(email)
    if not e:
        return None
    existing = get_suppression(db, e)
    if existing is not None:
        return existing
    domain = e.split("@", 1)[1] if "@" in e else None
    row = SuppressionEntry(
        email=e,
        domain=domain,
        reason=reason,
        source_run_id=source_run_id,
        note=note,
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_suppression(db: Session, limit: int = 500) -> list[SuppressionEntry]:
    return (
        db.query(SuppressionEntry)
        .order_by(SuppressionEntry.created_at.desc())
        .limit(limit)
        .all()
    )


def count_suppression(db: Session) -> int:
    return db.query(SuppressionEntry.id).count()


def get_suppression_by_id(db: Session, entry_id: int) -> SuppressionEntry | None:
    return db.query(SuppressionEntry).filter(SuppressionEntry.id == entry_id).first()


def delete_suppression(db: Session, entry_id: int) -> bool:
    """Remove a do-not-contact entry (manual override — e.g. a wrongly-flagged address).
    Returns False if the id doesn't exist."""
    row = get_suppression_by_id(db, entry_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
