"""Per-run Prompt setup + Signature (canonical storage; legacy: runs.context_json / runs.sender_signature_html)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text, String
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
    osint_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_search_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_osint_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    osint_discovery_mode: Mapped[str] = mapped_column(String(50), default="hardcore", nullable=False)
    language: Mapped[str] = mapped_column(String(50), default="Russian", nullable=False)
    sender_signature_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    run: Mapped["Run"] = relationship("Run", back_populates="run_setup")
