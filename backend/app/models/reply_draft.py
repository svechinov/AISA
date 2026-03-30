from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReplyDraft(Base):
    __tablename__ = "reply_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id"), nullable=False, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False, index=True)

    reply_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    attached_asset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
