"""Фаза 2, Task 8: при кастомном run_setups.draft_prompt запрет писать концовку самодостаточен.

Свой промпт кампании заменяет дефолтный блок целиком — вместе с буллетами «Hard requirements»,
на которые ссылается дописываемая ниже фраза. Для FG (первая кампания со своим draft_prompt) эта
ссылка указывала бы в никуда, а вместе с ней пропадал бы и явный запрет на прощание/подпись.
Кампании без своего draft_prompt (AlexStaff, NODA12) обязаны получать прежний текст ДОСЛОВНО.
0 tokens: generate_json застаблен."""

from __future__ import annotations

import importlib
import pkgutil

import app.models as _models_pkg

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fg_preset as fg_seed  # noqa: E402
import seed_noda12_preset as noda_seed  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run, get_run  # noqa: E402

VERBATIM_DEFAULT_NOTE = (
    "Do NOT write a closing paragraph yourself — see the 'Hard requirements' bullet above."
)
BODY = (
    # Длиннее плановой заготовки: generate_email_draft отбраковывает тело короче 120 символов
    # (outreach_email_pipeline.py: `if len(body) < 120: raise ValueError("Email body too short")`),
    # а исходная плановая строка (~88 символов) в этот порог не проходила — расхождение плана
    # с реальностью, тест адаптирован по смыслу без изменения проверяемой логики.
    "Здравствуйте, Мария!\n\n"
    "Первый абзац письма про отрасль и её текущие вызовы для компании Комбинат.\n\n"
    "Второй абзац письма про решение, конкретный первый шаг и пользу для вашей команды."
)


def _capture_prompt(fresh_db, monkeypatch, run, contact):
    from app.services import outreach_email_pipeline as pipeline

    captured = {}

    def fake_generate_json(prompt, task_kind=None, cache_prefix=None):
        captured["prompt"] = (cache_prefix or "") + prompt
        return {"subject": "Тема для Комбината", "body": BODY}

    monkeypatch.setattr(pipeline, "generate_json", fake_generate_json)
    reasoning = {"hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": ""}
    pipeline.generate_email_draft(
        fresh_db, run, contact, reasoning,
        prompt_setup_text=run.run_setup.prompt_setup_text, master_variant=None,
        style_mode="default", pers={"vacancy_signals": None}, finale_variant_index=0,
    )
    return captured["prompt"]


def _run_with(fresh_db, persona, setup_fields, name):
    proj = create_project(fresh_db, name=name, type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    setup = RunSetup(run_id=run.id)
    fresh_db.add(setup)
    for field, value in setup_fields.items():
        setattr(setup, field, value)
    fresh_db.commit()
    run = get_run(fresh_db, run.id)
    contact = Contact(run_id=run.id, name="Мария", email="m@closing-note.example.com",
                      company="Комбинат", source_json={})
    fresh_db.add(contact)
    fresh_db.commit()
    return run, contact


def test_campaign_without_own_draft_prompt_keeps_the_verbatim_note(fresh_db, monkeypatch):
    """Регресс AlexStaff/NODA12: ветка else обязана остаться дословной."""
    persona = noda_seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    text_fields, scalar_fields = noda_seed._canon_fields_for_profile("consulting")
    run, contact = _run_with(fresh_db, persona, {**text_fields, **scalar_fields}, "ClosingNoteDefault")

    prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)

    assert run.run_setup.draft_prompt is None  # предпосылка теста: свой промпт не задан
    assert VERBATIM_DEFAULT_NOTE in prompt


def test_campaign_with_own_draft_prompt_gets_a_self_contained_ban(fresh_db, monkeypatch):
    persona = fg_seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    text_fields, scalar_fields = fg_seed.canon_fields("metallurgy", frame=2)
    run, contact = _run_with(fresh_db, persona, {**text_fields, **scalar_fields}, "ClosingNoteCustom")

    prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)

    assert run.run_setup.draft_prompt  # предпосылка теста: свой промпт задан
    assert "see the 'Hard requirements' bullet above" not in prompt
    assert "no farewell line" in prompt
    assert "no sign-off" in prompt


def test_both_branches_still_say_the_closing_is_appended(fresh_db, monkeypatch):
    """Общая часть смысла не должна разъехаться между ветками."""
    noda_persona = noda_seed._seed_persona_noda12(fresh_db)
    fg_persona = fg_seed._seed_persona_fg(fresh_db)
    fresh_db.commit()

    noda_text, noda_scalar = noda_seed._canon_fields_for_profile("consulting")
    run_a, contact_a = _run_with(fresh_db, noda_persona, {**noda_text, **noda_scalar}, "ClosingNoteA")
    fg_text, fg_scalar = fg_seed.canon_fields("metallurgy", frame=1)
    run_b, contact_b = _run_with(fresh_db, fg_persona, {**fg_text, **fg_scalar}, "ClosingNoteB")

    for run, contact in ((run_a, contact_a), (run_b, contact_b)):
        prompt = _capture_prompt(fresh_db, monkeypatch, run, contact)
        assert "is appended to your body automatically after you write it" in prompt
