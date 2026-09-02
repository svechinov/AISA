"""Фаза 2, Task 1: настраиваемый потолок авторской части письма.

NULL в run_setups.max_authored_words = сегодняшнее поведение ДОСЛОВНО (180 слов и текст ошибки
про «120-140 words»); заданное значение поднимает потолок и меняет текст на нейтральный — «120-140»
это целевой диапазон под потолок 180, переносить его на чужой лимит значит выдумывать диапазон.
0 tokens: гейт детерминирован, критик застаблен."""

from __future__ import annotations

import app.services.hard_rules_gate as g
import app.services.outreach_email_pipeline  # noqa: F401 — регистрирует ORM-модели (mapper config)
from app.services.run_context_service import get_max_authored_words


def _body(word_count: int) -> str:
    """Тело, у которого авторская часть — ровно word_count слов (строка приветствия не считается)."""
    return "Hi Steve,\n\n" + " ".join(["word"] * word_count)


# --- Гейт: фоллбэк ------------------------------------------------------------------------------

def test_default_limit_and_wording_are_unchanged():
    issues = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens")
    assert any(
        "HARD RULE 4:" in i["detail"] and "120-140 words" in i["detail"] and "has 200" in i["detail"]
        for i in issues
    ), issues


def test_none_is_the_same_as_not_passing_it():
    a = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens")
    b = g.check_hard_rules("Hiring at Gardens", _body(200), company_name="Gardens", max_authored_words=None)
    assert a == b


# --- Гейт: заданный лимит -----------------------------------------------------------------------

def test_raised_limit_lets_a_longer_body_through():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(240), company_name="Gardens", max_authored_words=280,
    )
    assert not any("HARD RULE 4:" in i["detail"] for i in issues), issues


def test_raised_limit_still_catches_the_essay():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(320), company_name="Gardens", max_authored_words=280,
    )
    assert any(
        "HARD RULE 4:" in i["detail"] and "under 280 words" in i["detail"] for i in issues
    ), issues


def test_lowered_limit_is_honored_too():
    issues = g.check_hard_rules(
        "Hiring at Gardens", _body(150), company_name="Gardens", max_authored_words=100,
    )
    assert any("under 100 words" in i["detail"] for i in issues), issues


# --- Резолвер из RunSetup -----------------------------------------------------------------------

class _RS:
    def __init__(self, value):
        self.max_authored_words = value


class _Run:
    def __init__(self, rs):
        self.run_setup = rs


def test_get_max_authored_words_reads_the_run_setup():
    assert get_max_authored_words(_Run(_RS(280))) == 280


def test_get_max_authored_words_is_none_when_unset_or_absurd():
    assert get_max_authored_words(_Run(_RS(None))) is None
    assert get_max_authored_words(_Run(_RS(0))) is None
    assert get_max_authored_words(_Run(_RS("не число"))) is None
    assert get_max_authored_words(_Run(None)) is None
    assert get_max_authored_words(None) is None


# --- Сквозная проводка через валидацию -----------------------------------------------------------

def test_validate_outbound_email_threads_the_limit(monkeypatch):
    """Письмо на 240 слов: с дефолтом — hard_rule_violation, с лимитом 280 — чисто."""
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

    body = _body(240)
    strict = evs.validate_outbound_email(
        "Hiring at Gardens", body, {"vacancy_signals": None}, [],
        email_kind="vacancy", company_name="Gardens",
    )
    assert any(i["code"] == "hard_rule_violation" for i in strict["issues"]), strict["issues"]

    relaxed = evs.validate_outbound_email(
        "Hiring at Gardens", body, {"vacancy_signals": None}, [],
        email_kind="vacancy", company_name="Gardens", max_authored_words=280,
    )
    assert not any(i["code"] == "hard_rule_violation" for i in relaxed["issues"]), relaxed["issues"]
