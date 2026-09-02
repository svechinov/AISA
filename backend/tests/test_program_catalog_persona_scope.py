"""Фаза 2, Task 2: каталог программ скоупится по персоне.

Семантика NULL — «виден всем»: инстанс партнёра, где persona_id ни у одной строки не проставлен,
получает тот же каталог, что и до фазы. Наши сидеры обязаны проставлять persona_id всегда —
иначе на одном инстансе матчер подставит FG-адресату сессию NODA12. 0 tokens: LLM застаблен."""

from __future__ import annotations

import app.services.program_matcher as pm
from app.models.persona import Persona
from app.models.training_program import TrainingProgram


def _two_personas(fresh_db):
    a = Persona(slug="scope-a", display_name="A")
    b = Persona(slug="scope-b", display_name="B")
    fresh_db.add_all([a, b])
    fresh_db.flush()
    return a, b


def _catalog(fresh_db, persona_a, persona_b):
    own = TrainingProgram(name="Своя программа", target_pains=["боль А"], bullets=["б"],
                          persona_id=persona_a.id)
    alien = TrainingProgram(name="Чужая программа", target_pains=["боль Б"], bullets=["б"],
                            persona_id=persona_b.id)
    shared = TrainingProgram(name="Общая программа", target_pains=["общая боль"], bullets=["б"],
                             persona_id=None)
    fresh_db.add_all([own, alien, shared])
    fresh_db.commit()
    return own, alien, shared


def _stub(monkeypatch, program_id):
    calls = {}

    def fake(prompt, task_kind=None):
        calls["prompt"] = prompt
        return {"program_id": program_id, "fit_score": 90, "solution_text": "S", "rationale": "r"}

    monkeypatch.setattr(pm, "complete_prompt_json_object", fake)
    return calls


def test_persona_sees_its_own_and_global_but_not_alien(fresh_db, monkeypatch):
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    calls = _stub(monkeypatch, own.id)

    match = pm.match_program(fresh_db, problem="боль А", persona_id=a.id)

    assert match and match["program_id"] == own.id
    assert "Своя программа" in calls["prompt"]
    assert "Общая программа" in calls["prompt"]
    assert "Чужая программа" not in calls["prompt"]


def test_no_persona_id_keeps_the_whole_catalog(fresh_db, monkeypatch):
    """Фоллбэк: вызов без persona_id (партнёрский инстанс, прямые вызовы) видит весь каталог."""
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    calls = _stub(monkeypatch, own.id)

    pm.match_program(fresh_db, problem="боль А")

    assert "Своя программа" in calls["prompt"]
    assert "Чужая программа" in calls["prompt"]
    assert "Общая программа" in calls["prompt"]


def test_alien_program_id_from_the_model_is_refused(fresh_db, monkeypatch):
    """Даже если LLM вернёт id вне выборки — матч не собирается (программа не найдена в списке)."""
    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    _stub(monkeypatch, alien.id)

    assert pm.match_program(fresh_db, problem="боль А", persona_id=a.id) is None


def test_pipeline_passes_the_run_persona_into_the_matcher(fresh_db, monkeypatch):
    """_apply_program_match резолвит персону рана сам — вызывающему пайплайну ничего не менять."""
    import app.services.outreach_email_pipeline as oep
    from app.repositories.project_repo import create_project
    from app.repositories.run_repo import create_run

    a, b = _two_personas(fresh_db)
    own, alien, shared = _catalog(fresh_db, a, b)
    captured = {}

    def fake_match(db, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(pm, "match_program", fake_match)

    proj = create_project(fresh_db, name="ScopeTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = a.id
    fresh_db.commit()

    oep._apply_program_match(fresh_db, run, {"problem": "боль А"}, {})

    assert captured["persona_id"] == a.id


def test_seed_noda12_offers_stamp_the_persona(fresh_db):
    """Наш сидер обязан проставлять persona_id — включая повторный прогон по уже засеянным строкам."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_noda12_preset as seed

    legacy = TrainingProgram(name=seed.OFFERS[0]["name"], target_pains=["x"], bullets=["y"])
    fresh_db.add(legacy)
    fresh_db.commit()
    assert legacy.persona_id is None

    persona = seed._seed_persona_noda12(fresh_db)
    seed._seed_offers(fresh_db, persona_id=persona.id)
    fresh_db.commit()

    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)  # существующая строка обновлена, не продублирована
    assert all(r.persona_id == persona.id for r in rows)
