from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False, index=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id"), nullable=True, index=True)

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    provider_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    classification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    classification_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
