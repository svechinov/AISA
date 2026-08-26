"""B-273: deterministic HARD RULES gate. The four add-on drafts of 29.07 scored 100/100 from the
LLM critic with 2-4 canon violations each — these checks catch the literal-shape rules mechanically,
before any LLM call."""

import app.services.hard_rules_gate as g
import app.services.outreach_email_pipeline  # noqa: F401 — registers ORM models (mapper config)
from app.services.email_validation_service import validate_outbound_email

FINALE = "Happy to jump on a 15-minute call — or share a written summary first, whichever is lighter."


def _body(hook, who_we_are="We're AlexStaff - an IT-recruiting agency recruiting for game studios since 2006.",
          help_par="We can help. Not by forwarding CV piles, but by bringing candidates who want to join Turtle Rock.",
          salutation="Hi Steve,"):
    return "\n\n".join([salutation, hook, who_we_are, help_par, FINALE])


# --- HARD RULE 6: subject names the company ----------------------------------------------------

def test_subject_without_company_name_flagged():
    issues = g.check_hard_rules("Staffing your new studio", _body("You shipped Back 4 Blood."), company_name="Turtle Rock")
    assert any("HARD RULE 6:" in i["detail"] for i in issues)


def test_subject_with_company_name_clean():
    issues = g.check_hard_rules("Hiring at Turtle Rock", _body("You shipped Back 4 Blood."), company_name="Turtle Rock")
    assert not any("HARD RULE 6:" in i["detail"] for i in issues)


def test_company_check_skipped_when_name_all_generic():
    # "The Game Studio" has no distinctive token — the rule is not decidable, not violated.
    issues = g.check_hard_rules("Hello", _body("You shipped a game."), company_name="The Game Studio")
    assert not any("HARD RULE 6:" in i["detail"] for i in issues)


# --- HARD RULE 8: no posting attributes in the subject / hook ----------------------------------

def test_role_count_with_city_in_subject_flagged():
    # Live defect: "four Irvine roles" in the subject line.
    issues = g.check_hard_rules(
        "Four Irvine roles at Second Dinner", _body("You are staffing up."), company_name="Second Dinner"
    )
    assert any("HARD RULE 8:" in i["detail"] for i in issues)


def test_remote_attribute_in_hook_flagged():
    # Live defect: "both fully remote across the US and Canada".
    issues = g.check_hard_rules(
        "Hiring at Bonfire",
        _body("Your two openings are both fully remote across the US and Canada."),
        company_name="Bonfire",
    )
    assert any("HARD RULE 8:" in i["detail"] for i in issues)


def test_seniority_grade_in_hook_flagged():
    issues = g.check_hard_rules(
        "Hiring at Bonfire", _body("You are looking for a Senior Unity Developer."), company_name="Bonfire"
    )
    assert any("HARD RULE 8:" in i["detail"] for i in issues)


def test_plain_role_naming_is_allowed():
    issues = g.check_hard_rules(
        "Hiring at Bonfire", _body("Your careers page shows an artist and a Unity developer."), company_name="Bonfire"
    )
    assert not any("HARD RULE 8:" in i["detail"] for i in issues)


def test_attribute_later_in_body_is_allowed():
    # HARD RULE 8 explicitly permits an attribute later on when it carries our offer.
    body = _body(
        "Your careers page shows an artist and a Unity developer.",
        help_par="Remote roles are no problem: we source worldwide for Bonfire, in 24-72 hours after terms.",
    )
    issues = g.check_hard_rules("Hiring at Bonfire", body, company_name="Bonfire")
    assert not any("HARD RULE 8:" in i["detail"] for i in issues)


# --- HARD RULE 9 / 15: sign-off and em dash ----------------------------------------------------

def test_sign_off_in_body_flagged():
    body = _body("You shipped Back 4 Blood.") + "\n\nBest,\nAlexey"
    issues = g.check_hard_rules("Hiring at Turtle Rock", body, company_name="Turtle Rock")
    assert any("HARD RULE 9:" in i["detail"] for i in issues)


def test_em_dash_in_authored_text_flagged():
    issues = g.check_hard_rules(
        "Hiring at Turtle Rock", _body("You shipped Back 4 Blood — a big live-service bet."), company_name="Turtle Rock"
    )
    assert any("HARD RULE 15:" in i["detail"] for i in issues)


def test_em_dash_inside_the_appended_finale_is_exempt():
    # The verbatim closing is inserted as-is and legitimately contains an em dash.
    issues = g.check_hard_rules(
        "Hiring at Turtle Rock",
        _body("You shipped Back 4 Blood."),
        company_name="Turtle Rock",
        fixed_blocks=[FINALE],
    )
    assert not any("HARD RULE 15:" in i["detail"] for i in issues)


# --- HARD RULE 1 / 4: promise names the company, who-we-are is the second paragraph -------------

def test_promise_without_company_name_flagged():
    body = _body(
        "You are staffing up.",
        help_par="We can help. Within 24-72 hours you meet a first candidate who fits the role.",
    )
    issues = g.check_hard_rules("Hiring at Gardens", body, company_name="Gardens")
    assert any("HARD RULE 1:" in i["detail"] for i in issues)


def test_promise_with_company_name_clean():
    body = _body(
        "You are staffing up.",
        help_par="We can help. Within 24-72 hours you meet a first candidate who wants to join Gardens.",
    )
    issues = g.check_hard_rules("Hiring at Gardens", body, company_name="Gardens")
    assert not any("HARD RULE 1:" in i["detail"] for i in issues)


def test_who_we_are_out_of_second_paragraph_flagged():
    # Live defect (Second Dinner): the who-we-are block slipped to the third paragraph, so the
    # letter never said who we are until the signature.
    body = "\n\n".join([
        "Hi Steve,",
        "You are staffing up.",
        "We can help. Within 24-72 hours you meet a candidate who wants to join Second Dinner.",
        "We're AlexStaff - an IT-recruiting agency recruiting for game studios since 2006.",
        FINALE,
    ])
    issues = g.check_hard_rules("Hiring at Second Dinner", body, company_name="Second Dinner")
    assert any("HARD RULE 4:" in i["detail"] and "who-we-are" in i["detail"] for i in issues)


def test_structure_check_skipped_for_no_vacancy():
    body = "\n\n".join([
        "Hi Steve,",
        "One co-founder to another.",
        "When you do open a seat - engineer, artist, designer - we can help.",
        "We're AlexStaff - an IT-recruiting agency recruiting for game studios since 2006.",
    ])
    issues = g.check_hard_rules("Hiring at Gardens", body, company_name="Gardens", check_structure=False)
    assert not any("HARD RULE 4:" in i["detail"] for i in issues)


def test_overlong_body_flagged():
    long_par = " ".join(["word"] * 200)
    issues = g.check_hard_rules("Hiring at Gardens", _body(long_par), company_name="Gardens")
    assert any("HARD RULE 4:" in i["detail"] and "120-140 words" in i["detail"] for i in issues)


# --- Company name recovered from personalization ------------------------------------------------

def test_company_name_from_personalization():
    pers = {"company_facts": ["Named organization: Turtle Rock Studios.", "Founded 2002."]}
    assert g.company_name_from_personalization(pers) == "Turtle Rock Studios"
    assert g.company_name_from_personalization({}) is None


# --- Wiring: a HARD RULE violation is critical and blocks the LLM critic ------------------------

def test_validate_outbound_email_rejects_hard_rule_violation(monkeypatch):
    import app.services.email_validation_service as evs

    called = {"critic": 0}
    monkeypatch.setattr("app.services.llm_gateway.llm_configured", lambda: True)
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda *a, **k: called.__setitem__("critic", called["critic"] + 1) or {},
    )
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])  # cheap-tier NER, not the rubric
    out = validate_outbound_email(
        "Four Irvine roles at Second Dinner",
        _body("You are staffing up."),
        {"company_facts": ["Named organization: Second Dinner."]},
        [],
        email_kind="vacancy",
        company_name="Second Dinner",
    )
    assert out["is_valid"] is False
    assert any(i["code"] == "hard_rule_violation" for i in out["issues"])
    # The gate runs BEFORE the taste rubric — no LLM tokens are spent on a draft that breaks canon.
    assert called["critic"] == 0
