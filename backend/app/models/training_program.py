"""Training-program catalog: the concrete offers the matcher plugs into the email `solution` slot.

Each row is one FG program (или программа партнёра) with the pains it targets and an optional
PDF asset (assets.id) that gets auto-attached to generated drafts when the program is matched.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TrainingProgram(Base):
    __tablename__ = "training_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pains this program addresses — matcher input (list of short strings).
    target_pains: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Who it is for (e.g. "коммерческие директора", "HR/T&D").
    audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Delivery format (e.g. "2-дневный тренинг", "фасилитационная сессия", "экспресс-аудит").
    format: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Selling bullets surfaced in the email solution slot (list of short strings).
    bullets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Optional one-pager / brochure PDF in the asset library; auto-attached on match.
    asset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
