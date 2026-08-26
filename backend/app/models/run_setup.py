"""Per-run Prompt setup + Signature (canonical storage; legacy: runs.context_json / runs.sender_signature_html)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Text, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.run import Run


class RunSetup(Base):
    __tablename__ = "run_setups"

    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    prompt_setup_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canon of judgement (B-077 etap 2): editable per-run critic taste-rubric text, symmetric with
    # prompt_setup_text — code default lives in app.services.critic_canon.DEFAULT_CRITIC_CANON.
    critic_canon_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    osint_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_search_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_osint_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    osint_discovery_mode: Mapped[str] = mapped_column(String(50), default="api_only", nullable=False)
    language: Mapped[str] = mapped_column(String(50), default="English", nullable=False)
    sender_signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Configurable ICP filter (Phase 6). Employee-count band: NULL = no bound on that side
    # (set per campaign by the seed/UI). icp_criteria_json holds the other editable criteria
    # (industry keywords, regions, revenue band, min_company_age_years) — applied
    # deterministically BEFORE the LLM fit judge. Unknown size/criteria are NOT a reject.
    icp_min_employees: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    icp_max_employees: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    icp_criteria_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Fork-transition Phase 1, Task 6: overrides the AI-fit judge's "competitor, not buyer" rule
    # (run_company_ai_fit_service.DEFAULT_FIT_EXCLUSION_RULES) for campaigns whose own offer is
    # itself training/consulting-adjacent, where the default's worked example could otherwise read
    # every real buyer as a same-offer competitor. Empty/NULL = default text verbatim.
    fit_exclusion_rules_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run: Mapped["Run"] = relationship("Run", back_populates="run_setup")
