from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GmailProcessedMessage(Base):
    """Dedupe Gmail-driven tracking (e.g. bounces) so we do not apply the same notification twice."""

    __tablename__ = "gmail_processed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
