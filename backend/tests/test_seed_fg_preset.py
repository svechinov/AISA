"""Фаза 2, Task 5: пресет FG — персона + матрица «отрасль × рамка».

Рамки (решение C владельца 02.09): Рамка-1 «ревю отрасли + у вас на предприятии → одно решение»
(матчер работает, лимит дефолтный); Рамка-2 «ревю отрасли → веер программ» (матчер выключен,
лимит повышен). Контента FG ещё нет — сидер обязан помечать плейсхолдеры и не писать их в ран
без явного --allow-placeholders (урок noda12: не сеять несуществующий контент). 0 tokens."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fg_preset as seed  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.training_program import TrainingProgram  # noqa: E402
from app.services.persona_service import FG_SLUG  # noqa: E402


# --- Персона ------------------------------------------------------------------------------------

def test_seed_persona_fg_creates_row(fresh_db):
    persona = seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    assert persona.slug == FG_SLUG
    assert persona.no_signal_template_enabled is False  # у FG нет рекрутингового §2.3-шаблона
    assert persona.languages_json == ["Russian"]


def test_seed_persona_fg_idempotent(fresh_db):
    seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    assert fresh_db.query(Persona).filter(Persona.slug == FG_SLUG).count() == 1


# --- Матрица «отрасль × рамка» --------------------------------------------------------------------

def test_frames_differ_in_matcher_and_limit():
    _, scalar1 = seed.canon_fields("metallurgy", frame=1)
    _, scalar2 = seed.canon_fields("metallurgy", frame=2)

    assert scalar1["program_match_enabled"] is True
    assert scalar1["max_authored_words"] is None  # дефолт движка, решение D

    assert scalar2["program_match_enabled"] is False
    assert scalar2["max_authored_words"] == seed.FRAME2_MAX_WORDS


def test_frames_carry_different_draft_prompts():
    text1, _ = seed.canon_fields("metallurgy", frame=1)
    text2, _ = seed.canon_fields("metallurgy", frame=2)
    assert text1["draft_prompt"] != text2["draft_prompt"]
    assert "ОДНО решение" in text1["draft_prompt"]
    assert "веер программ" in text2["draft_prompt"].lower()


def test_both_frames_gate_the_minihook_on_a_strong_occasion():
    """Решение E: личный минихук — только при ярком недавнем поводе, и только из промпта пресета."""
    for frame in (1, 2):
        text, _ = seed.canon_fields("metallurgy", frame=frame)
        prompt = text["draft_prompt"].lower()
        assert "минихук" in prompt and "только при ярком недавнем поводе" in prompt


def test_industry_appears_in_the_prompt_setup():
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert "metallurgy" in text["prompt_setup_text"]


def test_signature_is_empty_for_the_export_channel():
    """Решение B/O: письма шлют менеджеры со своих ящиков; пустая подпись ещё и блокирует отправку
    движком (email_sender.validate_outbound_draft_sendable)."""
    for frame in (1, 2):
        text, _ = seed.canon_fields("metallurgy", frame=frame)
        assert text["sender_signature_html"] == ""


def test_default_fit_exclusion_rules_are_kept():
    """У FG покупатель — предприятие отрасли, конкурент — другой провайдер обучения: дефолт верен."""
    from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES

    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert text["fit_exclusion_rules_text"] == DEFAULT_FIT_EXCLUSION_RULES


# --- Защита от плейсхолдеров -----------------------------------------------------------------------

def test_unknown_industry_is_flagged_as_placeholder():
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert seed.PLACEHOLDER_MARKER in text["prompt_setup_text"]
    assert seed.has_placeholders(text) is True


def test_known_industry_has_no_placeholders(monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия",
        "review": "Реальное ревю отрасли от FG.",
        "programs": [{"name": "Программа 1", "pitch": "Одно предложение о сути."}],
    })
    text, _ = seed.canon_fields("metallurgy", frame=1)
    assert seed.PLACEHOLDER_MARKER not in text["prompt_setup_text"]
    assert seed.has_placeholders(text) is False


def test_apply_refuses_placeholders_without_the_flag(fresh_db):
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    proj = create_project(fresh_db, name="FGGuard", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    fresh_db.commit()

    with pytest.raises(SystemExit):
        seed.apply_canon(fresh_db, run, "metallurgy", frame=1, allow_placeholders=False)

    from app.models.run_setup import RunSetup

    assert fresh_db.query(RunSetup).filter(RunSetup.run_id == run.id).first() is None


def test_apply_writes_when_placeholders_are_allowed(fresh_db):
    from app.models.run_setup import RunSetup
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    proj = create_project(fresh_db, name="FGWrite", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    fresh_db.commit()

    seed.apply_canon(fresh_db, run, "metallurgy", frame=2, allow_placeholders=True)
    fresh_db.commit()

    setup = fresh_db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
    assert setup is not None
    assert setup.language == "Russian"
    assert setup.program_match_enabled is False
    assert setup.max_authored_words == seed.FRAME2_MAX_WORDS
    assert setup.sender_signature_html == ""


# --- Каталог программ FG ---------------------------------------------------------------------------

def test_seed_offers_scopes_programs_to_the_fg_persona(fresh_db, monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия",
        "review": "Реальное ревю.",
        "programs": [{"name": "Программа 1", "pitch": "Суть."},
                     {"name": "Программа 2", "pitch": "Суть."}],
    })
    persona = seed._seed_persona_fg(fresh_db)
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()

    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == 2
    assert all(r.persona_id == persona.id for r in rows)


def test_seed_offers_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setitem(seed.INDUSTRY_CONTENT, "metallurgy", {
        "label": "Металлургия", "review": "Ревю.",
        "programs": [{"name": "Программа 1", "pitch": "Суть."}],
    })
    persona = seed._seed_persona_fg(fresh_db)
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    fresh_db.commit()
    assert fresh_db.query(TrainingProgram).count() == 1
