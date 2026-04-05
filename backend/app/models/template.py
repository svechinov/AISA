from datetime import datetime

from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.template_variable import TemplateVariable


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    template_type: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Legacy; prefer template_variables rows. Kept {} after migration.
    variables_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    variable_rows: Mapped[list["TemplateVariable"]] = relationship(
        "TemplateVariable",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateVariable.name",
    )
