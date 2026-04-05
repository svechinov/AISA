"""Template variable defaults (replaces templates.variables_json)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.template import Template


class TemplateVariable(Base):
    __tablename__ = "template_variables"
    __table_args__ = (UniqueConstraint("template_id", "name", name="uq_template_variables_template_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    template: Mapped["Template"] = relationship("Template", back_populates="variable_rows")
