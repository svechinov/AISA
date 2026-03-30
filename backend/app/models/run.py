from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Outreach brief (run = context): drives company search, contact roles, master email.
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    master_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canonical storage for subject/body; legacy columns kept in sync for compatibility.
    master_email: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    master_email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    master_email_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Rich-text (HTML) signature for this run; appended on send for outreach + reply drafts.
    sender_signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)
