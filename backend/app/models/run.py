from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.run_setup import RunSetup

from app.models.run_company import RunCompany  # noqa: E402 — after Base; used for relationship order_by


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
    # Legacy: prefer run_setups.sender_signature_html; kept for back-compat until fully migrated.
    sender_signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    run_setup: Mapped["RunSetup | None"] = relationship(
        "RunSetup",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
    )
    run_companies: Mapped[list[RunCompany]] = relationship(
        RunCompany,
        back_populates="run",
        cascade="all, delete-orphan",
        order_by=RunCompany.collect_index.asc(),
    )
    # Optional voice for outbound generation: direct | warm | sharp | executive (used in later stages).
    email_style_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
