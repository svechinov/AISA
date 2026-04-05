from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.contact_personalization import ContactPersonalization


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")
    confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: Legacy; prefer entity_json_kv scope contact_source. Kept {} after migration.
    source_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Legacy; prefer contact_personalization + contact_personalization_facts. Kept {} after migration.
    personalization_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    personalization_row: Mapped["ContactPersonalization | None"] = relationship(
        "ContactPersonalization",
        back_populates="contact",
        uselist=False,
        cascade="all, delete-orphan",
    )

    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    email_health: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    last_contact_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Gmail inbox history check (Contact analyzer); NULL = not verified yet.
    gmail_history_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gmail_history_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Last successful «Import 6 months» from Gmail (inbox+sent) into email_threads/messages.
    gmail_inbox_imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
