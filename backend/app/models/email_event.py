from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    #: Remainder only (keys not mapped to typed columns).
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload_source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    email_thread_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_threads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reply_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("reply_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    inbound_from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inbound_to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inbound_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_delivery_issue: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    send_provider_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_rfc_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    send_to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    send_from_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_attachment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_attachment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply_attached_asset_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
