"""Тестовая отправка одного письма на свой ящик (проверка связки Gmail без порчи боевых черновиков).

Зачем копия, а не отправка оригинала: боевые черновики Cyprus-пилота должны остаться нетронутыми
(to_email реального ЛПР, review_status=pending для будущей ручной отправки). Здесь мы клонируем
черновик, подменяем получателя на свой адрес, помечаем approved и гоним через тот же код-путь,
что и API (send_one_draft): сборка HTML+подписи, отправка через Gmail, события queued/sent, тред.

Запуск из backend/:
    ./venv/bin/python scripts/send_test_draft_to_self.py                # отправить тест (копия черновика 1)
    ./venv/bin/python scripts/send_test_draft_to_self.py --source 3     # взять другой черновик за основу
    ./venv/bin/python scripts/send_test_draft_to_self.py --to me@x.com  # другой адрес-получатель
    ./venv/bin/python scripts/send_test_draft_to_self.py --cleanup 42   # удалить тестовую строку 42 и её следы

Требует EMAIL_PROVIDER=gmail + GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN в .env.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# --- load .env into os.environ (провайдеры читают os.environ напрямую) ---
_envf = pathlib.Path(__file__).resolve().parents[1] / ".env"
for line in _envf.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402 — регистрирует мапперы всех моделей
from app.models.email_draft import EmailDraft  # noqa: E402
from app.repositories.email_draft_repo import get_email_draft  # noqa: E402
from app.services.email_sender import send_one_draft  # noqa: E402

DEFAULT_TO = os.environ.get("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency").strip()


def _make_test_copy(db, source_id: int, to_email: str) -> EmailDraft:
    src = get_email_draft(db, source_id)
    if not src:
        raise SystemExit(f"Исходный черновик {source_id} не найден в БД.")

    copy = EmailDraft(
        run_id=src.run_id,
        contact_id=src.contact_id,
        company=src.company,
        to_email=to_email,
        subject=f"[TEST] {src.subject}",
        body=src.body,
        status="draft",
        review_status="approved",  # чтобы пройти validate_outbound_draft_sendable
        review_notes="Тестовая копия для проверки доставки Gmail (send_test_draft_to_self.py).",
        tracking_status=src.tracking_status,
        attached_asset_ids=list(src.attached_asset_ids or []),
        pipeline_source="test_self_send",
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy


def _cleanup(db, draft_id: int) -> None:
    """Удалить тестовую строку и её следы (события, сообщения, тред), чтобы не искажать счётчик sent."""
    from app.models.email_event import EmailEvent
    from app.models.email_message import EmailMessage
    from app.models.email_thread import EmailThread

    draft = get_email_draft(db, draft_id)
    if not draft:
        raise SystemExit(f"Черновик {draft_id} не найден — нечего чистить.")
    if (draft.pipeline_source or "") != "test_self_send":
        raise SystemExit(
            f"Черновик {draft_id} не помечен как тестовый (pipeline_source != 'test_self_send'). "
            "Отказ во избежание удаления боевой строки."
        )

    threads = db.query(EmailThread).filter(EmailThread.draft_id == draft_id).all()
    thread_ids = [t.id for t in threads]

    msgs = db.query(EmailMessage).filter(EmailMessage.draft_id == draft_id).delete(synchronize_session=False)
    if thread_ids:
        msgs += db.query(EmailMessage).filter(EmailMessage.thread_id.in_(thread_ids)).delete(
            synchronize_session=False
        )
    events = db.query(EmailEvent).filter(EmailEvent.draft_id == draft_id).delete(synchronize_session=False)
    for t in threads:
        db.delete(t)
    db.delete(draft)
    db.commit()
    print(f"Очищено: draft={draft_id}, threads={len(thread_ids)}, messages={msgs}, events={events}.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Тестовая отправка письма на свой ящик через Gmail.")
    ap.add_argument("--source", type=int, default=1, help="ID исходного черновика (по умолчанию 1).")
    ap.add_argument("--to", default=DEFAULT_TO, help=f"Адрес-получатель (по умолчанию {DEFAULT_TO}).")
    ap.add_argument("--cleanup", type=int, metavar="DRAFT_ID", help="Удалить тестовый черновик и его следы.")
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        if args.cleanup is not None:
            _cleanup(db, args.cleanup)
            return

        copy = _make_test_copy(db, args.source, args.to)
        print(f"Создана тестовая копия черновика: id={copy.id}, to={copy.to_email}, subject={copy.subject!r}")
        print("Отправка через Gmail…")
        result = send_one_draft(db, copy.id)

        db.expire_all()
        sent = get_email_draft(db, copy.id)
        print("\n=== Результат ===")
        print(f"status:              {result.get('status')}")
        print(f"provider_message_id: {result.get('provider_message_id')}")
        print(f"error:               {result.get('error')}")
        print(f"draft.status в БД:   {sent.status}")
        print(f"draft.thread_id:     {sent.thread_id}")
        print(f"\nТестовый draft_id = {copy.id}")
        if result.get("status") == "sent":
            print(f"Проверь ящик {args.to}. После подтверждения очисти:")
            print(f"    ./venv/bin/python scripts/send_test_draft_to_self.py --cleanup {copy.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
