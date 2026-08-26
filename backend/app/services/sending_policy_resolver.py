"""Which sending policy actually governs a run's outbound mail (B-547).

Прецедент 18.08: панель «Система» на дашборде звала get_default_policy(db) безусловно — для рана
персоны anastasia (шлёт с account-manager@, окно до 18:00) показывалась политика alex@ (окно
09:00–14:30), из-за чего дважды перепроверяли ящик на сервере и назвали неверный дедлайн аппрува.

Резолвер — ТОЛЬКО ЧТЕНИЕ для витрины: повторяет ту же цепочку, что enqueue_draft
(app/services/send_queue_service.py), но ничего не ставит в очередь и не шлёт. Сам enqueue_draft
не трогаем.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.repositories.sending_policy_repo import get_default_policy, get_policy_for_mailbox
from app.services.persona_service import get_run_persona

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.persona import Persona
    from app.models.run import Run
    from app.models.sending_policy import SendingPolicy


def resolve_policy_for_run(
    db: "Session", run: "Run | None",
) -> tuple["SendingPolicy | None", str, "Persona | None"]:
    """Return (policy, source, persona) for the mailbox that will actually send this run's mail.

    source:
      - "default" — no run, or run.persona_id is NULL (грабля проекта: NULL молча резолвится в
        персону alexey — здесь это НЕ считается run_persona, иначе витрина уверенно соврёт).
      - "run_persona" — run has an explicit persona_id and that persona's mailbox has a policy row.
      - "none" — persona is explicit but its mailbox has no sending_policy row: enqueue_draft would
        NOT queue this run's drafts, so the dashboard must say that instead of showing an unrelated
        default policy.
    """
    if run is None or getattr(run, "persona_id", None) is None:
        return get_default_policy(db), "default", None

    persona = get_run_persona(db, run)
    mailbox = (getattr(persona, "primary_mailbox_email", None) or "").strip()
    policy = get_policy_for_mailbox(db, mailbox) if mailbox else None
    if policy is None:
        return None, "none", persona
    return policy, "run_persona", persona
