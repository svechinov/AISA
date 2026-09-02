"""ПРИЁМКА Фазы 2 (гейт фазы, п. 3): обе рамки FG проходят пайплайн на чистой БД.

Смыкает четыре задачи фазы: настраиваемый лимит (Task 1), скоуп каталога по персоне (Task 2),
выключатель матчера (Task 3) и пресет FG (Task 5). Рамка-1 — письмо с ОДНИМ решением от матчера
в дефолтный лимит; рамка-2 — письмо-веер, матчер не вызывается, потолок FRAME2_MAX_WORDS.
0 tokens: generate_json, матчер и критик застаблены."""

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

import seed_fg_preset as seed  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run, get_run  # noqa: E402
from app.services.persona_service import FG_FINALES_JSON, fg_persona_kwargs  # noqa: E402

FG_RU_FINALE = FG_FINALES_JSON["segments"]["default"]["variants"]["ru"]

# Авторская часть рамки-1: ~60 слов, укладывается в канонные 180.
FRAME1_BODY = (
    "Здравствуйте, Мария!\n\n"
    "В отрасли сейчас заметно тянут сроки переделов: смены сдают партии неровно, "
    "и планирование едет.\n\n"
    "У вас на предприятии это обычно видно по простоям на стыке участков. Мы собираем "
    "разбор таких стыков с линейными руководителями за один день и даём им общий язык "
    "для планирования смен."
)

# Авторская часть рамки-2: ~240 слов — больше канонных 180, но меньше FRAME2_MAX_WORDS=280.
FRAME2_BODY = (
    "Здравствуйте, Мария!\n\n"
    "В отрасли сейчас заметно тянут сроки переделов, и планирование едет следом.\n\n"
    + " ".join(["слово"] * 225)
)


def _fg_run(fresh_db, frame: int):
    persona = seed._seed_persona_fg(fresh_db)
    fresh_db.commit()
    proj = create_project(fresh_db, name=f"FGSeam{frame}", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    seed.seed_offers(fresh_db, "metallurgy", persona_id=persona.id)
    seed.apply_canon(fresh_db, run, "metallurgy", frame=frame, allow_placeholders=True)
    fresh_db.commit()
    run = get_run(fresh_db, run.id)
    contact = Contact(run_id=run.id, name="Мария", email="maria@fg-seam.example.com",
                      company="Комбинат", role="Директор по персоналу", source_json={})
    fresh_db.add(contact)
    fresh_db.commit()
    return run, contact, persona


def _stub_critic(monkeypatch):
    import app.services.email_validation_service as evs
    import app.services.llm_gateway as gw

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(
        gw, "complete_prompt_json_object",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
            "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
        },
    )
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])


def test_frame1_uses_the_matcher_and_the_default_limit(fresh_db, monkeypatch):
    import app.services.outreach_email_pipeline as pipeline
    import app.services.program_matcher as pm

    run, contact, persona = _fg_run(fresh_db, frame=1)
    calls = {"matcher": 0}

    def fake_match(db, **kwargs):
        calls["matcher"] += 1
        calls["persona_id"] = kwargs.get("persona_id")
        return {"program_id": 1, "name": "П", "asset_id": None, "format": "f", "bullets": ["b"],
                "solution_text": "Разбор стыков участков за один день", "rationale": "r",
                "fit_score": 90}

    monkeypatch.setattr(pm, "match_program", fake_match)
    captured = {}

    def fake_generate_json(prompt, task_kind=None, cache_prefix=None):
        captured["prompt"] = (cache_prefix or "") + prompt
        return {"subject": "Планирование смен на Комбинате", "body": FRAME1_BODY}

    monkeypatch.setattr(pipeline, "generate_json", fake_generate_json)

    reasoning = {"hook": "", "angle": "", "problem": "простои на стыках", "solution": "generic",
                 "cta_type": "", "key_point": "generic"}
    match = pipeline._apply_program_match(fresh_db, run, reasoning, {})
    _subject, body = pipeline.generate_email_draft(
        fresh_db, run, contact, reasoning,
        prompt_setup_text=run.run_setup.prompt_setup_text, master_variant=None,
        style_mode="default", pers={"vacancy_signals": None}, finale_variant_index=0,
    )

    assert calls["matcher"] == 1
    assert calls["persona_id"] == persona.id  # каталог сужен до персоны FG (Task 2)
    assert match and reasoning["solution"] == "Разбор стыков участков за один день"
    assert "ОДНО решение" in captured["prompt"]  # draft_prompt рамки-1 доехал до генерации
    assert "AlexStaff" not in captured["prompt"]
    assert body.endswith(FG_RU_FINALE)


def test_frame1_letter_passes_the_gate_and_gets_a_rubric_score(fresh_db, monkeypatch):
    import app.services.email_validation_service as evs

    _stub_critic(monkeypatch)
    persona = Persona(**fg_persona_kwargs())
    body = f"{FRAME1_BODY}\n\n{FG_RU_FINALE}"

    result = evs.validate_outbound_email(
        "Планирование смен на Комбинате", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
    )

    codes = [i["code"] for i in result["issues"]]
    assert "hard_rule_violation" not in codes, result["issues"]
    assert "no_vacancy_template_drift" not in codes, codes
    assert result["critic_taste_pass"] is True
    assert result["is_valid"] is True, result["issues"]


def test_frame2_skips_the_matcher(fresh_db, monkeypatch):
    import app.services.outreach_email_pipeline as pipeline
    import app.services.program_matcher as pm

    run, _contact, _ = _fg_run(fresh_db, frame=2)
    calls = {"matcher": 0}

    def fake_match(db, **kwargs):
        calls["matcher"] += 1
        return None

    monkeypatch.setattr(pm, "match_program", fake_match)
    reasoning = {"problem": "простои на стыках", "solution": "generic", "key_point": "generic"}

    assert pipeline._apply_program_match(fresh_db, run, reasoning, {}) is None
    assert calls["matcher"] == 0
    assert reasoning["solution"] == "generic"


def test_frame2_long_letter_passes_only_under_the_raised_limit(fresh_db, monkeypatch):
    """То же тело: под каноном движка — нарушение HARD RULE 4, под лимитом рамки-2 — чисто."""
    import app.services.email_validation_service as evs
    from app.services.run_context_service import get_max_authored_words

    _stub_critic(monkeypatch)
    run, _contact, _ = _fg_run(fresh_db, frame=2)
    persona = Persona(**fg_persona_kwargs())
    body = f"{FRAME2_BODY}\n\n{FG_RU_FINALE}"

    assert get_max_authored_words(run) == seed.FRAME2_MAX_WORDS

    strict = evs.validate_outbound_email(
        "Программы для Комбината", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
    )
    assert any(i["code"] == "hard_rule_violation" for i in strict["issues"])

    relaxed = evs.validate_outbound_email(
        "Программы для Комбината", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[FG_RU_FINALE], company_name="Комбинат",
        max_authored_words=get_max_authored_words(run),
    )
    assert not any(i["code"] == "hard_rule_violation" for i in relaxed["issues"]), relaxed["issues"]
    assert relaxed["is_valid"] is True, relaxed["issues"]


def test_fg_run_cannot_send_anything(fresh_db):
    """Гейт фазы, п. 5: пустая подпись FG-рана физически блокирует отправку."""
    from app.services.run_context_service import get_sender_signature_html

    run, _contact, _ = _fg_run(fresh_db, frame=1)
    assert (get_sender_signature_html(run) or "").strip() == ""


def test_fg_catalog_is_invisible_to_another_persona(fresh_db, monkeypatch):
    """Гейт фазы, п. 5: программа FG не попадает в каталог чужой персоны (а глобальная — попадает)."""
    import app.services.program_matcher as pm
    from app.models.training_program import TrainingProgram

    _run, _contact, _fg_persona = _fg_run(fresh_db, frame=1)
    other = Persona(slug="other-seam", display_name="Other")
    fresh_db.add(other)
    # Глобальная строка нужна, чтобы выборка чужой персоны была НЕпустой: на пустом каталоге
    # match_program возвращает None до LLM-вызова, и тест доказывал бы не то.
    fresh_db.add(TrainingProgram(name="Глобальная программа", target_pains=["боль"],
                                 bullets=["б"], persona_id=None))
    fresh_db.commit()

    captured = {}

    def fake_llm(prompt, task_kind=None):
        captured["prompt"] = prompt
        return {"program_id": None, "fit_score": 0, "solution_text": "", "rationale": ""}

    monkeypatch.setattr(pm, "complete_prompt_json_object", fake_llm)
    pm.match_program(fresh_db, problem="любая боль", persona_id=other.id)

    assert "Глобальная программа" in captured["prompt"]
    assert seed.PLACEHOLDER_MARKER not in captured["prompt"]
