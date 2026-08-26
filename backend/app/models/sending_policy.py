from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SendingPolicy(Base):
    """Per-mailbox sending discipline: caps, send windows, warm-up ramp, follow-up cadence.

    One row per outbound mailbox. Scaling to several mailboxes later = adding rows; the worker
    already meters caps per mailbox. Follow-up cadence defaults live here (single-mailbox MVP).
    """

    __tablename__ = "sending_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    mailbox_email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    daily_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    hourly_cap: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    min_gap_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    gap_jitter_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=45)

    # Comma-separated weekday abbreviations (mon,tue,wed,thu,fri,sat,sun) allowed for each touch type.
    send_days_first_touch: Mapped[str] = mapped_column(String(64), nullable=False, default="tue,wed,thu")
    send_days_follow_up: Mapped[str] = mapped_column(String(64), nullable=False, default="mon,tue,wed,thu")

    # Local-time window in the policy timezone, "HH:MM".
    window_start: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    window_end: Mapped[str] = mapped_column(String(5), nullable=False, default="12:30")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Nicosia")

    # {"start": 5, "step_per_week": 5, "cap": 25, "started_on": "YYYY-MM-DD"}. Ramps daily_cap over weeks.
    warmup_ramp_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Follow-up cadence (touch 2+): wait N business days of silence, at most max_touches total.
    follow_up_after_business_days: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    max_touches: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
