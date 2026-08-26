"""B-077 etap 2 (Дельта приёмки #1): taste ≠ mechanics split — the LLM rubric's own pass/fail is
persisted separately from is_valid/issues, so the calibration matrix can compare taste vs Alex
instead of mechanics vs Alex."""

import sys
from pathlib import Path
from types import SimpleNamespace

import app.services.email_validation_service as evs
from app.utils.email_draft_generation_meta import (
    build_generation_meta_json_from_columns,
    generation_meta_dict_to_column_values,
)

VACANCY_PERS = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer"}]}}
# Canon-clean fixture (B-273): no em dash, no seniority grade recited back — the deterministic
# HARD RULES gate now runs before the critic, and a fixture that breaks canon would never
# reach the rubric these tests are about.
VACANCY_BODY = "Hi Alex,\n\nYou're hiring a Unity developer. Here is why we can help.\n\nA quick call?"

_PASSING_CRITIC_JSON = {
    "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
    "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
}

_FAILING_CRITIC_JSON = {
    "relevance_score": 1, "specificity_score": 1, "non_spam_score": 1,
    "cta_score": 1, "clarity_score": 1, "hook_grounded": True,
    "critique_issues": ["Too generic, no facts used."],
}


def _mock_critic(monkeypatch, verdict_json: dict):
    import app.services.llm_gateway as gw

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", lambda prompt, task_kind=None: dict(verdict_json))
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])


# --- validate_outbound_email: taste outcome on the result dict ---

def test_vacancy_passing_rubric_sets_taste_pass_true(monkeypatch):
    _mock_critic(monkeypatch, _PASSING_CRITIC_JSON)
    result = evs.validate_outbound_email(
        "Your Unity hire", VACANCY_BODY, VACANCY_PERS, [], email_kind=evs.EMAIL_KIND_VACANCY,
    )
    assert result["is_valid"] is True
    assert result["critic_taste_pass"] is True
    assert isinstance(result["critic_scores"], dict)
    assert set(result["critic_scores"]) == set(evs.CRITIC_RUBRIC_KEYS)
    assert result["critic_hook_grounded"] is True
    assert result["critic_canon_used"]
    assert isinstance(result["critic_evidence"], dict)


def test_vacancy_failing_rubric_sets_taste_pass_false(monkeypatch):
    _mock_critic(monkeypatch, _FAILING_CRITIC_JSON)
    result = evs.validate_outbound_email(
        "Your Unity hire", VACANCY_BODY, VACANCY_PERS, [], email_kind=evs.EMAIL_KIND_VACANCY,
    )
    assert result["is_valid"] is False
    assert result["critic_taste_pass"] is False


def test_no_vacancy_never_runs_taste_rubric(monkeypatch):
    from app.services.outreach_email_pipeline import NO_VACANCY_MIDDLE, NO_VACANCY_OPENERS

    import app.services.llm_gateway as gw

    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("LLM critic must not be called for no_vacancy emails")

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", _boom)
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])

    opener = NO_VACANCY_OPENERS["en"]["other"]
    middle = NO_VACANCY_MIDDLE["en"]
    body = f"Hi Alex,\n\n{opener}\n\n{middle}"
    result = evs.validate_outbound_email(
        "An early hello", body, {"vacancy_signals": None}, [],
        email_kind=evs.EMAIL_KIND_NO_VACANCY,
    )
    assert result["critic_taste_pass"] is None
    assert result["critic_scores"] is None
    assert result["critic_canon_used"] is None


# --- generation_meta column mapping + round-trip ---

def test_critic_taste_column_values_maps_meta_to_columns():
    meta = {
        "critic_scores": {
            "relevance_score": 4, "specificity_score": 3, "non_spam_score": 5,
            "cta_score": 4, "clarity_score": 5,
        },
        "critic_taste_pass": True,
        "critic_hook_grounded": True,
        "critic_canon_used": "some canon text",
        "critic_evidence": {"company_ev": "acme facts", "person_ev": None, "vacancy_ev": None},
    }
    cols = generation_meta_dict_to_column_values(meta)
    assert cols["critic_relevance_score"] == 4
    assert cols["critic_specificity_score"] == 3
    assert cols["critic_non_spam_score"] == 5
    assert cols["critic_cta_score"] == 4
    assert cols["critic_clarity_score"] == 5
    assert cols["critic_taste_pass"] is True
    assert cols["critic_hook_grounded"] is True
    assert cols["critic_canon_used"] == "some canon text"
    assert cols["critic_evidence_json"] == meta["critic_evidence"]


def test_critic_scores_round_trip_through_columns():
    meta = {
        "critic_scores": {
            "relevance_score": 4, "specificity_score": 3, "non_spam_score": 5,
            "cta_score": 4, "clarity_score": 5,
        },
        "critic_taste_pass": True,
        "critic_hook_grounded": True,
        "critic_canon_used": "some canon text",
        "critic_evidence": {"company_ev": "acme facts", "person_ev": None, "vacancy_ev": None},
        "pipeline_source": "llm",
    }
    cols = generation_meta_dict_to_column_values(meta)
    draft = SimpleNamespace(**cols)
    rebuilt = build_generation_meta_json_from_columns(draft)
    assert rebuilt["critic_scores"] == meta["critic_scores"]
    assert rebuilt["critic_taste_pass"] is True
    assert rebuilt["critic_canon_used"] == "some canon text"


# --- report bucketing: taste ≠ mechanics ---

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from critic_vs_alex_report import bucket_drafts  # noqa: E402


def _fake_draft(*, taste_pass, generation_is_valid, alex_verdict, draft_id=1):
    return SimpleNamespace(
        id=draft_id, company="Acme", validation_score=50.0,
        alex_verdict=alex_verdict, alex_verdict_why="because",
        critic_taste_pass=taste_pass, generation_is_valid=generation_is_valid,
    )


def test_mechanically_cut_draft_goes_to_cut_by_mechanics_not_nitpicks():
    d = _fake_draft(taste_pass=None, generation_is_valid=False, alex_verdict="ok_as_is")
    quadrants = bucket_drafts([d])
    assert quadrants["cut_by_mechanics"] == [d]
    assert quadrants["critic_nitpicks"] == []


def test_taste_fail_ok_as_is_is_critic_nitpicks():
    d = _fake_draft(taste_pass=False, generation_is_valid=False, alex_verdict="ok_as_is")
    quadrants = bucket_drafts([d])
    assert quadrants["critic_nitpicks"] == [d]


def test_taste_pass_would_not_send_is_critic_blind():
    d = _fake_draft(taste_pass=True, generation_is_valid=True, alex_verdict="would_not_send")
    quadrants = bucket_drafts([d])
    assert quadrants["critic_blind"] == [d]


def test_no_vacancy_lands_in_no_taste_verdict():
    d = _fake_draft(taste_pass=None, generation_is_valid=True, alex_verdict="ok_as_is")
    quadrants = bucket_drafts([d])
    assert quadrants["no_taste_verdict"] == [d]
    assert quadrants["cut_by_mechanics"] == []
