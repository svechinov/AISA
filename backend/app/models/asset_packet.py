from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AssetPacket(Base):
    __tablename__ = "asset_packets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("email_threads.id"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), nullable=True, index=True)
    reply_draft_id: Mapped[int | None] = mapped_column(ForeignKey("reply_drafts.id"), nullable=True, index=True)

    packet_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    packet_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
