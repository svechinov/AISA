from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DraftInstructLog(Base):
    """B-018/B-031: журнал инструктивных правок писем.

    Каждая принятая ревьюером правка («сделай короче последний абзац») пишется сюда —
    повторяющиеся инструкции это сигнал для канона промптов: B-031 анализирует журнал
    и предлагает изменения канона (human-in-the-loop, ничего не мутирует автоматически).
    """

    __tablename__ = "draft_instruct_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Явный Integer у FK-колонок: изолированное создание таблицы (тесты) не должно зависеть от
    # порядка регистрации email_drafts/runs в metadata для резолва типа.
    draft_id: Mapped[int] = mapped_column(Integer, ForeignKey("email_drafts.id"), nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("runs.id"), nullable=True, index=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
