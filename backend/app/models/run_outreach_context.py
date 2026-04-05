"""Labeled outreach brief fields (replaces runs.context_json[\"context\"] inner dict)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.run import Run


class RunOutreachContext(Base):
    __tablename__ = "run_outreach_context"

    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    offer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_entities: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_roles: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(120), nullable=False, default="Professional")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    run: Mapped["Run"] = relationship("Run", back_populates="outreach_context")
