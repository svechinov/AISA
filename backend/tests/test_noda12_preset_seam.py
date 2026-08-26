"""Fork-transition Phase 1 ACCEPTANCE (Task 8 gate): the seam test the plan required — proof that
Tasks 5+6+7 actually meet in one generated letter. A NODA12 (trek A) draft must: (a) be prompted
WITHOUT the AlexStaff recruiting no-vacancy template even though vacancy_signals is empty, (b) be
prompted in Russian, (c) end with the NODA12 ru finale (resolving language="Russian" -> "ru" for
the single "default" segment), and (d) validate through the LLM taste rubric — NOT the frozen
no_vacancy template-conformance path — with zero hard-rule violations, including HARD RULE 15
(em dash ban) NOT firing on the appended finale, which legitimately contains an em dash and is a
fixed block. 0 tokens: generate_json / the critic / NER are stubbed."""

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

import seed_noda12_preset as seed  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run, get_run  # noqa: E402
from app.services.persona_service import NODA12_FINALES_JSON, noda12_persona_kwargs  # noqa: E402

NODA12_RU_FINALE = NODA12_FINALES_JSON["segments"]["default"]["variants"]["ru"]

# Authored (LLM-written) part: RU, no AlexStaff blocks, no em dash, no banned phrases, <180 words.
AUTHORED_RU_BODY = (
    "Здравствуйте, Мария!\n\n"
    "Видел анонс вашей апрельской стратсессии по потокам создания ценности - формат с живой "
    "групповой работой, судя по отзывам, зашёл сильно.\n\n"
    "Для таких сессий есть инструмент сильнее стикеров: живая симуляция систем на общем экране. "
    "Группа собирает модель, жмёт пуск - и узкие места краснеют на глазах, а не в таблице цифр. "
    "Например, «Пивная игра» показывает эффект кнута за 45 минут без единого слайда."
)


def _make_noda12_run(fresh_db):
    persona = seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    proj = create_project(fresh_db, name="Noda12SeamTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    setup = RunSetup(run_id=run.id)
    fresh_db.add(setup)
    text_fields, scalar_fields = seed._canon_fields_for_profile("consulting")
    for field, value in {**text_fields, **scalar_fields}.items():
        setattr(setup, field, value)
    fresh_db.commit()
    run = get_run(fresh_db, run.id)
    contact = Contact(
        run_id=run.id, name="Мария", email="maria@seam-test.example.com",
        company="Мастерская фасилитации",
    )
    fresh_db.add(contact)
    fresh_db.commit()
    return run, contact, persona


def test_noda12_draft_prompt_has_no_recruiting_template_and_appends_ru_finale(fresh_db, monkeypatch):
    from app.services import outreach_email_pipeline as pipeline

    run, contact, _persona = _make_noda12_run(fresh_db)

    captured: dict = {}

    def _fake_generate_json(prompt, task_kind=None, cache_prefix=None):
        captured["prompt"] = prompt
        captured["cache_prefix"] = cache_prefix or ""
        return {"subject": "Живая симуляция для ваших стратсессий", "body": AUTHORED_RU_BODY}

    monkeypatch.setattr(pipeline, "generate_json", _fake_generate_json)

    reasoning = {"hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": ""}
    _subject, body = pipeline.generate_email_draft(
        fresh_db, run, contact, reasoning,
        prompt_setup_text=run.run_setup.prompt_setup_text, master_variant=None,
        style_mode="default", pers={"vacancy_signals": None}, finale_variant_index=0,
    )

    full_prompt = captured["cache_prefix"] + captured["prompt"]
    # (a) Task 5's toggle actually reached generation: no frozen recruiting template in the prompt.
    assert "NO-VACANCY OPENING" not in full_prompt
    assert "AlexStaff" not in full_prompt
    # (b) Russian is enforced at the prompt level (RunSetup.language via the consulting profile).
    assert "IN Russian" in captured["prompt"]
    # (c) The NODA12 ru finale resolved for segment "default" and was appended in code.
    assert body.endswith(NODA12_RU_FINALE)


def test_noda12_validation_uses_taste_rubric_not_template_conformance(monkeypatch):
    import app.services.email_validation_service as evs
    import app.services.llm_gateway as gw

    persona = Persona(**noda12_persona_kwargs())
    called = {"critic": False}

    def _fake_llm(prompt, task_kind=None, cache_prefix=None):
        if task_kind == "email_critic":
            called["critic"] = True
            return {
                "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
                "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
            }
        return {"roles": []}

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", _fake_llm)
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])

    body = f"{AUTHORED_RU_BODY}\n\n{NODA12_RU_FINALE}"
    # Subject carries the recipient company: HARD RULE 6 (a global canon rule, like HR15) requires
    # it, and a violation is critical — which would gate the taste rubric off and mask what this
    # test exists to prove. For NODA12 the rule is actually desirable (subject personalization).
    result = evs.validate_outbound_email(
        "Живая симуляция для сессий Мастерской фасилитации", body,
        {"vacancy_signals": None}, [],
        persona=persona,
        expected_finale_variants=[NODA12_RU_FINALE],
        company_name="Мастерская фасилитации",
    )

    codes = [i["code"] for i in result["issues"]]
    # The frozen-template path must NOT have judged this letter...
    assert "no_vacancy_template_drift" not in codes, codes
    # ...the taste rubric must have (email_kind derived as "vacancy" via the persona toggle).
    assert called["critic"] is True
    # Finale byte-gate satisfied; no hard-rule violations — including HARD RULE 15 on the
    # appended finale's legitimate em dash (it is a fixed block, excluded from the check).
    assert "finale_verbatim_mismatch" not in codes, codes
    assert "hard_rule_violation" not in codes, codes
    assert result["is_valid"] is True, result["issues"]


def test_ru_em_dash_in_authored_body_still_trips_hard_rule_15(monkeypatch):
    """HARD RULE 15 (no em dash in the authored part) applies to NODA12's Russian letters BY THE
    OWNER'S EXPLICIT DECISION (26.08.2026): the em dash is a telltale of AI-written text — in
    Russian too — so the rule is shared canon, not inherited AlexStaff baggage. Only the authored
    (LLM-written) part is checked: the verbatim finale is a fixed block excluded from the gate
    (AlexStaff's own alexey finales carry em dashes the same way). Score -30 with retries, not an
    auto-fail — the generator is pushed to hyphens/shorter sentences."""
    import app.services.email_validation_service as evs
    import app.services.llm_gateway as gw

    persona = Persona(**noda12_persona_kwargs())
    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(
        gw, "complete_prompt_json_object",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
            "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
        },
    )
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])

    dashed = AUTHORED_RU_BODY.replace(
        "инструмент сильнее стикеров:", "инструмент сильнее стикеров —",
    )
    body = f"{dashed}\n\n{NODA12_RU_FINALE}"
    result = evs.validate_outbound_email(
        "Живая симуляция для Мастерской фасилитации", body, {"vacancy_signals": None}, [],
        persona=persona, expected_finale_variants=[NODA12_RU_FINALE],
        company_name="Мастерская фасилитации",
    )
    assert any(
        i["code"] == "hard_rule_violation" and "15" in i["detail"] for i in result["issues"]
    ), result["issues"]
