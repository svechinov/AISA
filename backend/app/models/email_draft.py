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

    # B-147: which verbatim closing-paragraph variant (0-based index into persona.finales_json's
    # resolved segment options — A=0, B=1, C=2, ...) this draft was generated with. NULL = a
    # single-option segment (rotation not in effect for this draft) or a pre-B-147 draft.
    finale_variant: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Alex's verdict on this draft (B-077 etap 2: critic <-> Alex calibration). Coded values in
    # app.constants.alex_verdict.ALEX_VERDICTS; NULL = not yet reviewed. UI/fill-in is a later task.
    alex_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    alex_verdict_why: Mapped[str | None] = mapped_column(Text, nullable=True)
    alex_verdict_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # B-077 etap 2: исход LLM-рубрики вкуса, отделённый от механики (для матрицы калибровки).
    # None = рубрика не прогонялась (no_vacancy по дизайну / механический реджект до рубрики / LLM off).
    critic_taste_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    critic_relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critic_specificity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critic_non_spam_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critic_cta_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critic_clarity_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critic_hook_grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    critic_canon_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    critic_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
