"""Sender persona (B-071 stage A): self-representation, verbatim closing paragraphs, geo-segment
keyword tables, signature, languages — the identity read by outreach_email_pipeline /
geo_segment_service / email_validation_service instead of hardcoded constants. One row per persona
(e.g. "alexey"); runs.persona_id points here (NULL -> "alexey", the current single-tenant default,
decision 8, multitenancy-personas-handoff-2026-07-18.md).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Generic self-descriptor (NOT the verbatim finale text — that lives inside finales_json).
    self_intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Nicosia")
    languages_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Ordered "country/city -> segment key" keyword tables + default segment (decision 8/9, B-071).
    geo_map_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # segment x language -> verbatim closing-paragraph text + an explicit fallback chain
    # (decision 10, B-071) — no silent language substitution.
    finales_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proof_anchors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # This persona's default sending mailbox; real per-mailbox creds are stage B (not this stage).
    primary_mailbox_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Fork-transition Phase 1, Task 5: does this persona have a frozen recruiting-industry §2.3
    # fallback (NO_VACANCY_OPENERS/NO_VACANCY_MIDDLE) to fall back on when there's no vacancy
    # signal? NULL/True = current behavior (email_kind_for forces no_vacancy, the body must
    # reproduce the verbatim AlexStaff template). False = no signal still gets a freely-authored,
    # taste-rubric-judged letter (see email_kind_for in email_validation_service.py).
    no_signal_template_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
