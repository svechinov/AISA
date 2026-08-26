"""B-077 etap 2: canon of judgement as an editable artifact.

- validate_outbound_email(critic_canon=None) assembles a vacancy-critic prompt semantically
  identical to the pre-refactor hardcoded prompt (same key phrases, same 5 rubric keys, same
  JSON contract) — the default vacancy-critic behavior must not change.
- validate_outbound_email(critic_canon="...") replaces the default canon text in the prompt sent
  to the LLM (not adds to it) — the run-level canon is a substitution, not an append.
- no_vacancy path still never calls the LLM critic, even with a custom critic_canon set.
- get_critic_canon_text returns "" for a run with no run_setup / an empty critic_canon_text.
"""

from types import SimpleNamespace

import app.services.email_validation_service as evs
from app.services.critic_canon import DEFAULT_CRITIC_CANON
from app.services.run_context_service import get_critic_canon_text

VACANCY_PERS = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer"}]}}
# Canon-clean fixture (B-273): no em dash, no seniority grade recited back — the deterministic
# HARD RULES gate now runs before the critic, and a fixture that breaks canon would never
# reach the rubric these tests are about.
VACANCY_BODY = "Hi Alex,\n\nYou're hiring a Unity developer. Here is why we can help.\n\nA quick call?"

_PASSING_CRITIC_JSON = {
    "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
    "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
}


def _capture_prompt(monkeypatch):
    """Mock the LLM critic call to capture the prompt sent, return a valid passing verdict."""
    import app.services.llm_gateway as gw

    captured: dict[str, str] = {}

    def _fake_critic(prompt, task_kind=None):  # noqa: ANN001
        captured["prompt"] = prompt
        return dict(_PASSING_CRITIC_JSON)

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", _fake_critic)
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])
    return captured


# --- critic_canon=None: default behavior preserved ---

def test_default_canon_prompt_contains_key_phrases(monkeypatch):
    captured = _capture_prompt(monkeypatch)
    result = evs.validate_outbound_email(
        "Your Unity hire", VACANCY_BODY, VACANCY_PERS, [], email_kind=evs.EMAIL_KIND_VACANCY,
    )
    assert result["is_valid"] is True
    prompt = captured["prompt"]
    assert "elite B2B SDR Critic" in prompt
    assert "hook_grounded" in prompt
    assert "Scoring note" in prompt
    for key in evs.CRITIC_RUBRIC_KEYS:
        assert key in prompt


# --- critic_canon=<custom>: substitution, not addition ---

def test_custom_canon_replaces_default_in_prompt(monkeypatch):
    captured = _capture_prompt(monkeypatch)
    custom = "MARKER_CANON_XYZ — judge only on vibes."
    result = evs.validate_outbound_email(
        "Your Unity hire", VACANCY_BODY, VACANCY_PERS, [],
        email_kind=evs.EMAIL_KIND_VACANCY, critic_canon=custom,
    )
    assert result["is_valid"] is True
    prompt = captured["prompt"]
    assert "MARKER_CANON_XYZ" in prompt
    assert "elite B2B SDR Critic" not in prompt
    assert "Scoring note" not in prompt


# --- no_vacancy path: LLM critic never called, even with a custom canon ---

def test_no_vacancy_skips_llm_critic_even_with_custom_canon(monkeypatch):
    import app.services.llm_gateway as gw
    from app.services.outreach_email_pipeline import NO_VACANCY_MIDDLE, NO_VACANCY_OPENERS

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
        email_kind=evs.EMAIL_KIND_NO_VACANCY, critic_canon="MARKER_CANON_XYZ",
    )
    assert result["is_valid"] is True


# --- get_critic_canon_text ---

def test_get_critic_canon_text_no_run_setup():
    run = SimpleNamespace(run_setup=None)
    assert get_critic_canon_text(run) == ""


def test_get_critic_canon_text_empty_string():
    run = SimpleNamespace(run_setup=SimpleNamespace(critic_canon_text=""))
    assert get_critic_canon_text(run) == ""


def test_get_critic_canon_text_none_value():
    run = SimpleNamespace(run_setup=SimpleNamespace(critic_canon_text=None))
    assert get_critic_canon_text(run) == ""


def test_get_critic_canon_text_set_value():
    run = SimpleNamespace(run_setup=SimpleNamespace(critic_canon_text="  custom canon  "))
    assert get_critic_canon_text(run) == "custom canon"


def test_default_critic_canon_matches_hardcoded_key_phrases():
    """Sanity check that the extracted canon retains the phrases the prompt-assembly test relies on."""
    assert "elite B2B SDR Critic" in DEFAULT_CRITIC_CANON
    assert "hook_grounded" in DEFAULT_CRITIC_CANON
    assert "Scoring note" in DEFAULT_CRITIC_CANON
    for key in evs.CRITIC_RUBRIC_KEYS:
        assert key in DEFAULT_CRITIC_CANON
