"""B-018: instruct-edit — тонкая обвязка над шлюзом; проверяем контракт и tier-маршрутизацию."""

from unittest.mock import patch

import pytest

from app.services.draft_instruct_edit import instruct_edit_email


def test_instruct_edit_returns_all_fields_and_routes_to_strong_tier():
    reply = {"subject": "S", "body": "B", "subject_ru": "Тема", "body_ru": "Текст"}
    with patch(
        "app.services.draft_instruct_edit.complete_prompt_json_object",
        return_value=reply,
    ) as mocked:
        out = instruct_edit_email("old subject", "old body", "сделай короче последний абзац")

    assert out == reply
    prompt = mocked.call_args.args[0]
    assert "сделай короче последний абзац" in prompt
    assert "old body" in prompt
    assert mocked.call_args.kwargs.get("task_kind") == "draft_instruct_edit"


def test_instruct_edit_rejects_empty_result():
    with patch(
        "app.services.draft_instruct_edit.complete_prompt_json_object",
        return_value={"subject": "S", "body": "", "subject_ru": "", "body_ru": ""},
    ):
        with pytest.raises(ValueError):
            instruct_edit_email("s", "b", "инструкция")


def test_instruct_edit_russian_stays_russian_and_skips_translation_call():
    """B-546: письмо, написанное по-русски, не должно возвращаться правкой по-английски —
    промпт требует остаться на русском, и перевод не запрашивается (нет смысла переводить
    русский в русский): subject_ru/body_ru = сам результат."""
    reply = {"subject": "Новая тема", "body": "Новый текст письма"}
    with patch(
        "app.services.draft_instruct_edit.complete_prompt_json_object",
        return_value=reply,
    ) as mocked:
        out = instruct_edit_email("Старая тема", "Старый текст", "сократи", language="ru")

    assert out["subject"] == "Новая тема"
    assert out["body"] == "Новый текст письма"
    assert out["subject_ru"] == out["subject"]
    assert out["body_ru"] == out["body"]
    prompt = mocked.call_args.args[0]
    assert "stays in Russian" in prompt
    assert "stays in English" not in prompt


def test_instruct_edit_english_behavior_unchanged():
    """language="en" (явно и по умолчанию) — прежнее поведение: промпт требует остаться на
    английском и просит отдельный RU-перевод результата."""
    reply = {"subject": "S", "body": "B", "subject_ru": "Тема", "body_ru": "Текст"}
    with patch(
        "app.services.draft_instruct_edit.complete_prompt_json_object",
        return_value=reply,
    ) as mocked:
        out = instruct_edit_email("old subject", "old body", "сделай короче", language="en")

    assert out == reply
    prompt = mocked.call_args.args[0]
    assert "stays in English" in prompt
    assert "stays in Russian" not in prompt


def test_instruct_route_language_follows_draft_body_not_run_setup(db):
    """B-546: язык правки (и поле language в ответе) определяется языком САМОГО письма
    (pick_signature_language), не языком, зашитым в сетап рана — иначе русское письмо в
    англоязычном ране вернулось бы правкой по-английски."""
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.api.email_drafts import EmailDraftInstructIn, instruct_email_draft_route

    project = Project(name="instruct-lang-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="instruct-lang-run")
    db.add(run)
    db.commit()
    # Сетап рана — английский; тело письма ниже — русское, оно и должно победить.
    db.add(RunSetup(run_id=run.id, sender_signature_html="<p>Alexey</p>", language="English"))
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=99999999, company="Acme", to_email="x@example.com",
        subject="Тема письма", body="Текст письма по-русски", status="draft", review_status="pending",
    )
    db.add(draft)
    db.commit()

    reply = {"subject": "Новая тема", "body": "Новый текст"}
    with (
        patch("app.services.llm_gateway.llm_configured", return_value=True),
        patch("app.services.draft_instruct_edit.complete_prompt_json_object", return_value=reply),
    ):
        result = instruct_email_draft_route(draft.id, EmailDraftInstructIn(instruction="сократи"), db)

    assert result["language"] == "ru"
    assert result["body_ru"] == result["body"]


def test_instruct_apply_keeps_pending_draft_out_of_queue(db):
    """Код-ревью 2026-07-11: инструктивная правка pending-письма НЕ должна ставить его в очередь
    (иначе «Принять правку» молча = «Отправить»). Черновик остаётся pending, в send_queue его нет."""
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.repositories.send_queue_repo import get_by_draft
    from app.api.email_drafts import EmailDraftInstructApplyIn, instruct_apply_email_draft_route

    project = Project(name="instruct-apply-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="instruct-apply-run")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, sender_signature_html="<p>Alexey</p>"))
    db.commit()
    # contact_id указывает на несуществующий контакт → критик пропускается (без LLM-вызова)
    draft = EmailDraft(
        run_id=run.id, contact_id=99999999, company="Acme", to_email="x@example.com",
        subject="Original", body="Body", status="draft", review_status="pending",
    )
    db.add(draft)
    db.commit()

    payload = EmailDraftInstructApplyIn(subject="Edited subject", body="Edited body", instruction="короче")
    result = instruct_apply_email_draft_route(draft.id, payload, db)

    db.refresh(draft)
    assert draft.review_status == "pending", "правка не должна одобрять письмо"
    assert draft.subject == "Edited subject"
    assert get_by_draft(db, draft.id) is None, "pending-письмо не должно попасть в очередь"
    assert result.review_status == "pending"


def test_instruct_log_model_roundtrip(tmp_path):
    """B-031: журнал правок — модель пишется и читается (отдельная БД, без снапшота).
    Создаём всю схему (FK draft_id → email_drafts требует наличия таблицы-цели)."""
    import pkgutil
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models as models_pkg
    from app.db import Base
    from app.models.draft_instruct_log import DraftInstructLog

    # Регистрируем все модели в metadata, иначе FK-цель email_drafts не найдётся при create_all.
    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")

    engine = create_engine(f"sqlite:///{(tmp_path / 'log.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(DraftInstructLog(draft_id=25, run_id=2, instruction="сделай последний абзац короче"))
        s.commit()
        row = s.query(DraftInstructLog).one()
        assert row.instruction == "сделай последний абзац короче"
        assert row.draft_id == 25
        assert row.created_at is not None
