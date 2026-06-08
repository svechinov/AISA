from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000), nullable=True)
