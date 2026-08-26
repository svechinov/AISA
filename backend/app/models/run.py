from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.persona import Persona
    from app.models.run_master_email_variant import RunMasterEmailVariant
    from app.models.run_outreach_context import RunOutreachContext
    from app.models.run_setup import RunSetup

from app.models.run_company import RunCompany  # noqa: E402 — after Base; used for relationship order_by


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    #: Legacy; prefer input_goal + entity_json_kv scope run_input. Kept {} after migration.
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: From input_json.goal (canonical string).
    input_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Legacy; prefer run_outreach_context + entity_json_kv run_context_extra. Kept {} after migration.
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    master_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Legacy; prefer run_master_email_variants. Kept null after migration.
    master_email: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    master_email_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    master_email_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Legacy: prefer run_setups.sender_signature_html; kept for back-compat until fully migrated.
    sender_signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    outreach_context: Mapped["RunOutreachContext | None"] = relationship(
        "RunOutreachContext",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
    )
    master_email_variants: Mapped[list["RunMasterEmailVariant"]] = relationship(
        "RunMasterEmailVariant",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RunMasterEmailVariant.position",
    )
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
    # Professional profile slug (see email_style_service.VALID_PROFESSIONAL_PROFILES); drives outbound voice.
    email_style_mode: Mapped[str | None] = mapped_column(String(48), nullable=True)

    # B-071: sender persona for this run's outreach (self-intro, verbatim finales, geo-map).
    # NULL -> the "alexey" persona (current single-tenant default; decision 8, B-071 handoff).
    persona_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("personas.id"), nullable=True, index=True,
    )
    persona: Mapped["Persona | None"] = relationship("Persona")
