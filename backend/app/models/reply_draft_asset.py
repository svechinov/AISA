"""Ordered attachment of library assets to a reply draft."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReplyDraftAsset(Base):
    __tablename__ = "reply_draft_assets"
    __table_args__ = (UniqueConstraint("reply_draft_id", "asset_id", name="uq_reply_draft_assets_draft_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    reply_draft_id: Mapped[int] = mapped_column(
        ForeignKey("reply_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
