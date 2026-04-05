"""Generic key/value rows replacing JSON blobs on domain entities (value_json holds any JSON type)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EntityJsonKV(Base):
    __tablename__ = "entity_json_kv"
    __table_args__ = (
        UniqueConstraint("scope", "entity_id", "key", name="uq_entity_json_kv_scope_entity_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
