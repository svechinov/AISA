from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Suppression reasons.
REASON_NOT_INTERESTED = "not_interested"
REASON_DEAD_MAILBOX = "dead_mailbox"
REASON_BOUNCED = "bounced"
REASON_MANUAL = "manual"
REASON_UNSUBSCRIBE = "unsubscribe"


class SuppressionEntry(Base):
    """Do-not-contact registry, cross-run. An email here is never sent to again while the entry
    is in effect (see ``expires_at``).

    Auto-populated on ``not_interested`` replies and on dead_mailbox/bounce events; also editable by hand.
    ``email`` is stored lowercased for exact-match lookups.
    """

    __tablename__ = "suppression_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(50), nullable=False, default=REASON_MANUAL)
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # B-138: NULL = permanent (unsubscribe, dead_mailbox, bounced, manual — unchanged semantics).
    # A datetime is a cooldown: is_suppressed() ignores the row once expires_at is in the past.
    # Used for not_interested (6-month cooldown, decision 20.07) — a studio's open roles change.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
