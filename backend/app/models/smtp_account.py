from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func

from app.db import Base

class SmtpAccount(Base):
    __tablename__ = "smtp_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    
    smtp_server = Column(String, nullable=False, default="smtp.yandex.ru")
    smtp_port = Column(Integer, nullable=False, default=465)
    
    imap_server = Column(String, nullable=False, default="imap.yandex.ru")
    imap_port = Column(Integer, nullable=False, default=993)
    
    is_active = Column(Boolean, default=True)
    daily_limit = Column(Integer, default=50)
    
    # Tracking
    sent_today = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    reset_at = Column(DateTime(timezone=True), nullable=True)  # When sent_today resets

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
