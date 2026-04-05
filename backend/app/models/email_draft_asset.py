"""Ordered attachment of library assets to an outbound email draft (replaces JSON attached_asset_ids)."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EmailDraftAsset(Base):
    __tablename__ = "email_draft_assets"
    __table_args__ = (UniqueConstraint("email_draft_id", "asset_id", name="uq_email_draft_assets_draft_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email_draft_id: Mapped[int] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
