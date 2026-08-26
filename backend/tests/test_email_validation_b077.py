"""B-077 etap 1: the critic judges against the generation contract (email_kind).

- email_kind_for derives vacancy vs no_vacancy from personalization (mirrors has_open_roles).
- no_vacancy skips the LLM taste-rubric and validates §2.3 template conformance mechanically.
- a no_vacancy body that reproduces §2.3 verbatim is valid AND never calls the LLM critic
  (this is the Horns Up regression: the generator gave correct §2.3 text, the critic killed it).
- a no_vacancy body that drifted off the template is rejected as no_vacancy_template_drift.
"""

import app.services.email_validation_service as evs
from app.services.outreach_email_pipeline import NO_VACANCY_MIDDLE, NO_VACANCY_OPENERS

OPENER_EN = NO_VACANCY_OPENERS["en"]["other"]
MIDDLE_EN = NO_VACANCY_MIDDLE["en"]

# A faithful §2.3 no-vacancy body: standing opener + who-we-are/when-you-open middle + greeting.
CONFORMANT_NO_VACANCY_BODY = f"Hi Alex,\n\n{OPENER_EN}\n\n{MIDDLE_EN}"


def _no_llm(monkeypatch):
    """Make the LLM critic explode if it is ever called — proves the rubric was skipped."""
    import app.services.llm_gateway as gw

    def _boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("LLM critic must not be called for no_vacancy emails")

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", _boom)
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])


# --- email_kind_for derivation ---

def test_email_kind_for_no_vacancy_when_signals_empty():
    assert evs.email_kind_for({"vacancy_signals": None}) == evs.EMAIL_KIND_NO_VACANCY
    assert evs.email_kind_for({}) == evs.EMAIL_KIND_NO_VACANCY
    assert evs.email_kind_for({"vacancy_signals": {"open_roles": []}}) == evs.EMAIL_KIND_NO_VACANCY


def test_email_kind_for_vacancy_when_open_roles_present():
    pers = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer"}]}}
    assert evs.email_kind_for(pers) == evs.EMAIL_KIND_VACANCY


# --- no_vacancy: rubric skipped, mechanical conformance decides ---

def test_conformant_no_vacancy_is_valid_and_skips_llm_critic(monkeypatch):
    _no_llm(monkeypatch)
    result = evs.validate_outbound_email(
        "An early hello from AlexStaff",
        CONFORMANT_NO_VACANCY_BODY,
        {"vacancy_signals": None},
        [],
        email_kind=evs.EMAIL_KIND_NO_VACANCY,
    )
    assert result["is_valid"] is True
    assert not any(i["code"] == "no_vacancy_template_drift" for i in result["issues"])


def test_conformant_no_vacancy_kind_derived_when_not_passed(monkeypatch):
    """Same body, email_kind omitted — the default derivation must still skip the rubric."""
    _no_llm(monkeypatch)
    result = evs.validate_outbound_email(
        "An early hello", CONFORMANT_NO_VACANCY_BODY, {"vacancy_signals": None}, [],
    )
    assert result["is_valid"] is True


def test_drifted_no_vacancy_body_flagged_template_drift(monkeypatch):
    _no_llm(monkeypatch)
    body = "Hi Alex,\n\nI saw your studio online and wanted to reach out about working together.\n\nLet's chat."
    result = evs.validate_outbound_email(
        "Hello", body, {"vacancy_signals": None}, [], email_kind=evs.EMAIL_KIND_NO_VACANCY,
    )
    assert result["is_valid"] is False
    assert any(i["code"] == "no_vacancy_template_drift" for i in result["issues"])


def test_conformance_check_direct():
    assert evs._check_no_vacancy_conformance(CONFORMANT_NO_VACANCY_BODY) is None
    drift = evs._check_no_vacancy_conformance("Hi,\n\nRandom off-template pitch.\n\nBye.")
    assert drift is not None and drift["code"] == "no_vacancy_template_drift"


def test_opener_split_across_sentences_still_conforms():
    """Fix (review finding #1): if the LLM renders the opener as two sentences inside one paragraph,
    the paragraph-level opener match must still recognize it — no false drift reject."""
    split_opener = OPENER_EN.replace(" — ", ". ", 1)  # force an extra sentence boundary
    body = f"Hi Alex,\n\n{split_opener}\n\n{MIDDLE_EN}"
    assert evs._check_no_vacancy_conformance(body) is None


# --- vacancy path unaffected: the LLM rubric still runs ---

def test_vacancy_email_still_invokes_llm_critic(monkeypatch):
    import app.services.llm_gateway as gw

    called = {"n": 0}

    def _fake_critic(prompt, task_kind=None):  # noqa: ANN001
        called["n"] += 1
        return {
            "relevance_score": 5, "specificity_score": 5, "non_spam_score": 5,
            "cta_score": 5, "clarity_score": 5, "hook_grounded": True, "critique_issues": [],
        }

    monkeypatch.setattr(gw, "llm_configured", lambda: True)
    monkeypatch.setattr(gw, "complete_prompt_json_object", _fake_critic)
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])

    pers = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer"}]}}
    # Canon-clean fixture (B-273): the HARD RULES gate runs before the rubric.
    body = "Hi Alex,\n\nYou're hiring a Unity developer. Here is why we can help.\n\nA quick call?"
    result = evs.validate_outbound_email(
        "Your Unity hire", body, pers, [], email_kind=evs.EMAIL_KIND_VACANCY,
    )
    assert called["n"] == 1
    assert result["is_valid"] is True
