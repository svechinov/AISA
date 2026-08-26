from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Queue item states.
STATE_QUEUED = "queued"      # waiting for its slot (not_before) and a passing gate check
STATE_HELD = "held"          # a gate failed; hold_reason set; will not send until resolved
STATE_RELEASING = "releasing"  # picked by the worker for this tick (in-flight)
STATE_SENT = "sent"          # send_one_draft reported sent
STATE_CANCELED = "canceled"  # withdrawn by a human or superseded

ACTIVE_STATES = (STATE_QUEUED, STATE_HELD, STATE_RELEASING)


class SendQueueItem(Base):
    """One approved draft waiting to be released by the send-queue worker.

    Enqueued when a draft is approved; the planner assigns ``not_before`` (a concrete slot honoring
    the mailbox policy). The worker releases due items through the gates, then send_one_draft.
    """

    __tablename__ = "send_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id"), nullable=False, unique=True, index=True,
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    mailbox_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    touch_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Assigned slot; the worker only considers items with not_before <= now. NULL until planned.
    not_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    state: Mapped[str] = mapped_column(String(20), nullable=False, default=STATE_QUEUED, index=True)
    hold_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Why the last transient reschedule pushed this item to a new slot (GateResult.reason) —
    #: shown in the Send queue "Reason" column for queued items (B-026).
    last_reschedule_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
