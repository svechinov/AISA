from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False, index=True)

    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracking_status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Library asset ids to attach (order preserved).
    attached_asset_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # reasoning, validation_score, style_mode, etc. (populated in later pipeline stages).
    generation_meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Phase 1: canonical columns (kept in sync with generation_meta_json on write).
    prompt_setup_text_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_style_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    validation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_issues_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generation_is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    peer_similarity_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pipeline_source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reasoning_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_cta_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_key_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 5-slot skeleton (problem/solution) + Feature 1 matched program — without these the
    # startup blob backfill+strip would erase them on the first restart after generation.
    reasoning_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_program_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
