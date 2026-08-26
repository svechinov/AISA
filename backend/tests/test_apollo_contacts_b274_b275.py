"""B-274 (Apollo second pass over wider titles instead of an LLM fallback) and
B-275 (surname cross-checked against the contact's own LinkedIn profile)."""

import app.services.apollo_service as ap
from app.services.contact_name_check import (
    FLAG_KEY,
    annotate_surname_check,
    contact_surname_unverified,
    surname_matches_linkedin,
)


# --- B-274: second-pass titles ------------------------------------------------------------------

def test_fallback_titles_exclude_already_tried_ones():
    out = ap.fallback_person_titles(["CEO", "Recruiting", "founder"])
    assert "recruiting" not in out          # already asked for in the first pass
    assert "head of people" in out
    assert all(t not in ("ceo", "founder") for t in out)


def test_second_pass_runs_when_run_titles_find_nobody(monkeypatch):
    queries: list[list[str]] = []

    def _search(domain, titles, *, per_page):
        queries.append(list(titles))
        if len(queries) == 1:
            return {"people": []}          # the run's narrow titles: nobody
        return {"people": [{"id": "p1"}]}  # wider hiring-side titles: a real person

    monkeypatch.setattr(ap, "apollo_configured", lambda: True)
    monkeypatch.setattr(ap, "search_people_json", _search)
    monkeypatch.setattr(ap, "bulk_match_people", lambda ids: [
        {"id": "p1", "name": "Ann Lee", "title": "Head of People", "email": "ann@bonfire.test",
         "linkedin_url": "https://linkedin.com/in/annlee"},
    ])
    monkeypatch.setattr(ap, "apollo_llm_hints_for_run", lambda rid, run: (["tag"], ["ceo"]))
    monkeypatch.setattr(ap, "get_effective_context", lambda run: {})
    monkeypatch.setattr(ap, "push_human_ui_activity", lambda *a, **k: None)
    monkeypatch.setattr(ap, "push_human_ui_activity_once", lambda *a, **k: None)

    out = ap.try_find_contacts_via_apollo(
        db=None, run_id=1, run=object(),
        step_input={"companies": [{"name": "Bonfire", "website": "https://bonfire.test"}]},
    )

    assert len(queries) == 2                       # first pass, then the wider one
    assert "head of people" in queries[1]
    assert out["contacts"][0]["email"] == "ann@bonfire.test"


def test_no_second_pass_when_first_pass_found_people(monkeypatch):
    queries: list[list[str]] = []

    def _search(domain, titles, *, per_page):
        queries.append(list(titles))
        return {"people": [{"id": "p1"}]}

    monkeypatch.setattr(ap, "apollo_configured", lambda: True)
    monkeypatch.setattr(ap, "search_people_json", _search)
    monkeypatch.setattr(ap, "bulk_match_people", lambda ids: [
        {"id": "p1", "name": "Bob Ross", "title": "CEO", "email": "bob@studio.test"},
    ])
    monkeypatch.setattr(ap, "apollo_llm_hints_for_run", lambda rid, run: (["tag"], ["ceo"]))
    monkeypatch.setattr(ap, "get_effective_context", lambda run: {})
    monkeypatch.setattr(ap, "push_human_ui_activity", lambda *a, **k: None)
    monkeypatch.setattr(ap, "push_human_ui_activity_once", lambda *a, **k: None)

    ap.try_find_contacts_via_apollo(
        db=None, run_id=1, run=object(),
        step_input={"companies": [{"name": "Studio", "website": "https://studio.test"}]},
    )
    assert len(queries) == 1


# --- B-275: surname vs LinkedIn -----------------------------------------------------------------

def test_corrupted_surname_detected_live_case():
    # Apollo returned "Stephen Gamescom" for Stephen Bell (in/sbellgardens), title and address right.
    assert surname_matches_linkedin("Stephen Gamescom", "http://www.linkedin.com/in/sbellgardens") is False


def test_matching_surname_accepted():
    assert surname_matches_linkedin("Stephen Bell", "http://www.linkedin.com/in/sbellgardens") is True
    assert surname_matches_linkedin("Ann Lee", "https://linkedin.com/in/ann-lee-4b21") is True


def test_undecidable_cases_return_none():
    assert surname_matches_linkedin("Stephen Bell", None) is None          # no profile
    assert surname_matches_linkedin("Stephen", "https://linkedin.com/in/sbell") is None  # no surname
    assert surname_matches_linkedin("Stephen Bell", "https://example.com/x") is None     # not LinkedIn
    assert surname_matches_linkedin("Stephen Bell", "https://linkedin.com/in/sb12") is None  # opaque slug
    # Cyrillic name vs a latin slug is transliteration, not a mismatch.
    assert surname_matches_linkedin("Степан Белов", "https://linkedin.com/in/stepanbelov") is None


def test_annotate_flags_only_the_mismatch():
    bad = annotate_surname_check({"name": "Stephen Gamescom", "linkedin": "https://linkedin.com/in/sbellgardens"})
    good = annotate_surname_check({"name": "Stephen Bell", "linkedin": "https://linkedin.com/in/sbellgardens"})
    assert bad[FLAG_KEY] is True and "сверь имя" in bad["surname_check_note"]
    assert FLAG_KEY not in good


def test_contact_surname_unverified_reads_the_flag():
    assert contact_surname_unverified({FLAG_KEY: True}) is True
    assert contact_surname_unverified({}) is False
    assert contact_surname_unverified(None) is False


def test_apollo_contacts_carry_linkedin_and_flag(monkeypatch):
    monkeypatch.setattr(ap, "apollo_configured", lambda: True)
    monkeypatch.setattr(ap, "search_people_json", lambda d, t, *, per_page: {"people": [{"id": "p1"}]})
    monkeypatch.setattr(ap, "bulk_match_people", lambda ids: [
        {"id": "p1", "name": "Stephen Gamescom", "title": "Co-founder", "email": "stephen@gardens.test",
         "linkedin_url": "http://www.linkedin.com/in/sbellgardens"},
    ])
    monkeypatch.setattr(ap, "apollo_llm_hints_for_run", lambda rid, run: (["tag"], ["ceo"]))
    monkeypatch.setattr(ap, "get_effective_context", lambda run: {})
    monkeypatch.setattr(ap, "push_human_ui_activity", lambda *a, **k: None)
    monkeypatch.setattr(ap, "push_human_ui_activity_once", lambda *a, **k: None)

    out = ap.try_find_contacts_via_apollo(
        db=None, run_id=1, run=object(),
        step_input={"companies": [{"name": "Gardens", "website": "https://gardens.test"}]},
    )
    contact = out["contacts"][0]
    assert contact["linkedin"] == "http://www.linkedin.com/in/sbellgardens"
    assert contact[FLAG_KEY] is True


# --- B-275: the flag blocks generation until a human confirms the name --------------------------

def test_draft_generation_skipped_for_unverified_surname(monkeypatch):
    import app.workers.email_worker as ew
    from types import SimpleNamespace

    contact = SimpleNamespace(
        id=1, run_id=1, status="valid", review_status="approved", email="stephen@gardens.test",
    )
    monkeypatch.setattr(ew, "_surname_unverified", lambda db, c: True)
    monkeypatch.setattr(ew, "get_prompt_setup_text", lambda run: (_ for _ in ()).throw(AssertionError("generation started")))

    assert ew._compose_outreach_email_payload_for_contact(db=None, run=object(), contact=contact) is None
