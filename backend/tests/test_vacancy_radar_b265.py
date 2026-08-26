"""B-265: the company's own careers page outranks every weaker source in BOTH directions —
an explicit "no positions open" ends the cascade, and blog/social posts about hiring are dropped
from the weak stages. Network calls are always monkeypatched."""

import app.services.vacancy_radar as vr


# --- "No open positions" declared on the company's own careers page ---------------------------

def test_declares_no_openings_supergiant_wording():
    # The live case: studio site says this while the radar reported two roles from the blog + FB.
    assert vr.careers_page_declares_no_openings(
        "At the moment we have no positions open, but we're always glad to hear from you."
    )


def test_declares_no_openings_common_phrasings():
    for text in (
        "There are no open positions right now.",
        "We have no current openings.",
        "No vacancies at this time.",
        "We are not currently hiring.",
        "Сейчас нет открытых вакансий.",
    ):
        assert vr.careers_page_declares_no_openings(text), text


def test_hiring_careers_page_is_not_a_no_openings_declaration():
    for text in (
        "Open positions: Senior Unity Developer, 2D Artist. Apply now.",
        "We're hiring across engineering and art.",
        "",
    ):
        assert not vr.careers_page_declares_no_openings(text), text


def test_cascade_stops_on_declared_no_openings(monkeypatch):
    calls = {"ats": 0, "linkedin": 0, "general": 0, "llm": 0}
    monkeypatch.setattr(
        vr,
        "_corpus_from_careers_page",
        lambda website: (
            ["[Company careers page] At the moment we have no positions open. (https://supergiant.com/careers)"],
            ["https://supergiant.com/careers"],
        ),
    )
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda n, w=None: calls.__setitem__("ats", calls["ats"] + 1) or ([], []))
    monkeypatch.setattr(vr, "_corpus_from_linkedin_jobs", lambda n: calls.__setitem__("linkedin", calls["linkedin"] + 1) or ([], []))
    monkeypatch.setattr(vr, "_corpus_from_general_search", lambda n, w: calls.__setitem__("general", calls["general"] + 1) or ([], []))
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda *a, **k: calls.__setitem__("llm", calls["llm"] + 1) or {"is_hiring": True, "open_roles": [{"role": "Engineer"}]},
    )

    out = vr.collect_vacancy_signals("Supergiant Games", "supergiant.com")

    assert out is not None
    assert out["is_hiring"] is False
    assert out["declared_no_openings"] is True
    assert out["open_roles"] == []
    assert out["sources"] == ["https://supergiant.com/careers"]
    # No weaker source may outvote the studio's own statement — and no LLM call is spent on it.
    assert calls == {"ats": 0, "linkedin": 0, "general": 0, "llm": 0}


def test_careers_page_with_roles_still_extracts_normally(monkeypatch):
    monkeypatch.setattr(
        vr,
        "_corpus_from_careers_page",
        lambda website: (["[Company careers page] Open roles: Senior Unity Developer (https://x/careers)"], ["https://x/careers"]),
    )
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda *a, **k: {"is_hiring": True, "open_roles": [{"role": "Senior Unity Developer"}], "summary": "hiring"},
    )
    out = vr.collect_vacancy_signals("Nekki", "nekki.com")
    assert out and out["is_hiring"] is True and out["open_roles"][0]["role"] == "Senior Unity Developer"


# --- Blog / social posts are not evidence of an open role -------------------------------------

def test_weak_sources_recognized():
    for url in (
        "https://www.facebook.com/supergiantgames/posts/123",
        "https://x.com/supergiantgames/status/1",
        "https://supergiantgames.com/blog/we-are-hiring/",
        "https://medium.com/@studio/we-are-growing",
        "https://www.linkedin.com/pulse/hiring-spree-studio",
        "https://t.me/gamedev_jobs/42",
    ):
        assert vr.is_weak_hiring_source(url), url


def test_structured_listings_are_not_weak_sources():
    for url in (
        "https://nekki.com/careers",
        "https://job-boards.eu.greenhouse.io/turtlerock",
        "https://api.ashbyhq.com/posting-api/job-board/Joyteractive",
        "https://www.linkedin.com/jobs/view/123456",
    ):
        assert not vr.is_weak_hiring_source(url), url


def test_general_search_drops_blog_and_social_hits(monkeypatch):
    hits = [
        {"title": "We're hiring!", "url": "https://studio.com/blog/hiring", "snippet": "we are hiring engineers"},
        {"title": "FB post", "url": "https://facebook.com/studio/posts/1", "snippet": "join our team"},
        {"title": "Careers", "url": "https://studio.com/careers", "snippet": "Senior Unity Developer"},
    ]
    monkeypatch.setattr("app.services.search_service.search_configured", lambda: True)
    monkeypatch.setattr("app.services.search_service.search_web", lambda q, **k: hits)
    parts, urls = vr._corpus_from_general_search("Studio", "studio.com")
    assert urls == ["https://studio.com/careers"]
    assert len(parts) == 1


def test_linkedin_stage_drops_pulse_articles(monkeypatch):
    hits = [
        {"title": "Article", "url": "https://www.linkedin.com/pulse/we-are-hiring", "snippet": "hiring"},
        {"title": "Job", "url": "https://www.linkedin.com/jobs/view/99", "snippet": "Unity Developer"},
    ]
    monkeypatch.setattr("app.services.search_service.search_configured", lambda: True)
    monkeypatch.setattr("app.services.search_service.search_web", lambda q, **k: hits)
    parts, urls = vr._corpus_from_linkedin_jobs("Studio")
    assert urls == ["https://www.linkedin.com/jobs/view/99"]
    assert len(parts) == 1
