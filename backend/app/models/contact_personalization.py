"""Rule-based personalization strings (replaces contacts.personalization_json)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.contact import Contact


class ContactPersonalization(Base):
    __tablename__ = "contact_personalization"

    contact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_angle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    why_this_company: Mapped[str] = mapped_column(Text, nullable=False, default="")
    offer_fit: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risks_or_constraints: Mapped[str] = mapped_column(Text, nullable=False, default="")

    contact: Mapped["Contact"] = relationship("Contact", back_populates="personalization_row")
    facts: Mapped[list["ContactPersonalizationFact"]] = relationship(
        "ContactPersonalizationFact",
        back_populates="personalization",
        cascade="all, delete-orphan",
        order_by="ContactPersonalizationFact.position",
    )


class ContactPersonalizationFact(Base):
    __tablename__ = "contact_personalization_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("contact_personalization.contact_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    personalization: Mapped["ContactPersonalization"] = relationship(
        "ContactPersonalization",
        back_populates="facts",
    )
