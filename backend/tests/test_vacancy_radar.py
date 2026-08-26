"""Vacancy radar (B-062): source cascade (careers page -> ATS patterns -> LinkedIn -> general
search) -> LLM extraction -> structured hiring signal (or None). Network calls are always
monkeypatched — never rely on the sandbox's lack of internet access to make a stage fail."""

import app.services.vacancy_radar as vr


def _hits(*urls):
    return [{"title": "Careers", "url": u, "snippet": "We are hiring a Senior Unity Developer"} for u in urls]


# --- Pure URL/slug builders (item 13: ATS-slug + careers-URL construction) ---

def test_careers_url_candidates_from_website():
    urls = vr.careers_url_candidates("https://www.nekki.com/en")
    assert urls == [
        "https://nekki.com/careers",
        "https://nekki.com/jobs",
        "https://nekki.com/career",
        "https://nekki.com/vacancies",
    ]


def test_careers_url_candidates_empty_without_website():
    assert vr.careers_url_candidates(None) == []
    assert vr.careers_url_candidates("") == []


def test_careers_url_candidates_adds_scheme_when_missing():
    urls = vr.careers_url_candidates("nekki.com")
    assert urls[0] == "https://nekki.com/careers"


def test_company_slug_candidates_variants():
    slugs = vr.company_slug_candidates("OIJO Games")
    assert "OIJOGames" in slugs
    assert "oijo-games" in slugs


def test_company_slug_candidates_empty_for_blank_name():
    assert vr.company_slug_candidates("") == []
    assert vr.company_slug_candidates("   ") == []


def test_company_slug_candidates_strips_corp_suffix():
    # B-075: "Strikerz Inc." must not leak "Inc"/"Inc." into the slug (was producing a broken
    # double-dot hostname "strikerzinc..huntflow.io" and missing the real board slug "strikerz").
    slugs = vr.company_slug_candidates("Strikerz Inc.")
    assert "strikerz" in slugs
    assert not any("inc" in s.lower() for s in slugs)
    assert not any("." in s for s in slugs)


def test_company_slug_candidates_strips_ticker_parens():
    # B-075: "Nexters ($GDEV)" must not leak the ticker/parens into the slug.
    slugs = vr.company_slug_candidates("Nexters ($GDEV)")
    assert "nexters" in slugs
    assert not any(c in s for s in slugs for c in "($)")
    assert not any("gdev" in s.lower() for s in slugs)


def test_company_slug_candidates_unchanged_without_suffix():
    # Normal case (no corp suffix/punctuation) must keep producing the same slugs as before.
    slugs = vr.company_slug_candidates("OIJO Games")
    assert "OIJOGames" in slugs
    assert "oijo-games" in slugs
    assert vr.company_slug_candidates("Guli") == ["Guli", "guli"]


def test_ats_url_builders():
    assert vr.ashby_job_board_url("Joyteractive") == "https://api.ashbyhq.com/posting-api/job-board/Joyteractive"
    assert vr.greenhouse_job_board_url("ebaka") == "https://job-boards.eu.greenhouse.io/ebaka"
    assert vr.huntflow_job_board_url("Guli") == "https://guli.huntflow.io"
    assert vr.pinpoint_job_board_url("Strikerz") == "https://strikerz.pinpointhq.com"


def test_site_query_added_for_domain():
    queries = vr._vacancy_queries("Nekki", "https://www.nekki.com/en")
    assert any(q.startswith("site:nekki.com") for q in queries)
    assert len(queries) == 3


# --- Cascade ordering: each stage tried in order, first non-empty corpus wins ---

def test_careers_page_wins_when_it_has_content(monkeypatch):
    monkeypatch.setattr(
        "app.services.company_source_extractor._extract_page_text",
        lambda url: "We're hiring! Senior Unity Developer, 2D Artist." * 20 if url.endswith("/careers") else "",
    )
    parts, urls = vr._corpus_from_careers_page("https://nekki.com")
    assert parts and urls == ["https://nekki.com/careers"]


def test_careers_page_empty_when_no_candidate_has_real_content(monkeypatch):
    monkeypatch.setattr("app.services.company_source_extractor._extract_page_text", lambda url: "")
    parts, urls = vr._corpus_from_careers_page("https://nekki.com")
    assert parts == [] and urls == []


def test_cascade_stops_at_first_successful_stage(monkeypatch):
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: ([], []))
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda name, website=None: (["[Ashby job board] Senior Unity Developer — Warsaw (x)"], ["https://x"]))
    calls = {"linkedin": 0, "general": 0}
    monkeypatch.setattr(vr, "_corpus_from_linkedin_jobs", lambda name: calls.__setitem__("linkedin", calls["linkedin"] + 1) or ([], []))
    monkeypatch.setattr(vr, "_corpus_from_general_search", lambda name, website: calls.__setitem__("general", calls["general"] + 1) or ([], []))
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda prompt: {"is_hiring": True, "open_roles": [{"role": "Senior Unity Developer"}], "summary": "hiring"},
    )

    out = vr.collect_vacancy_signals("Joyteractive", "joyteractive.io")
    assert out is not None
    assert calls == {"linkedin": 0, "general": 0}  # ATS stage succeeded -> later stages never run


def test_falls_through_to_general_search_when_all_targeted_sources_miss(monkeypatch):
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: ([], []))
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda name, website=None: ([], []))
    monkeypatch.setattr(vr, "_corpus_from_linkedin_jobs", lambda name: ([], []))
    monkeypatch.setattr("app.services.search_service.search_configured", lambda: True)
    monkeypatch.setattr("app.services.search_service.search_web", lambda q, **k: _hits("https://nekki.com/careers"))
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda prompt: {
            "is_hiring": True,
            "open_roles": [{"role": "Senior Unity Developer", "seniority": "senior",
                             "location": "Limassol", "country": "Cyprus", "evidence_url": "https://nekki.com/careers"}],
            "summary": "Hiring: Senior Unity Developer (careers page)",
        },
    )
    out = vr.collect_vacancy_signals("Nekki", "https://nekki.com")
    assert out is not None and out["is_hiring"] is True
    assert out["open_roles"][0]["role"] == "Senior Unity Developer"
    assert out["open_roles"][0]["location"] == "Limassol"
    assert "https://nekki.com/careers" in out["sources"]


def test_no_evidence_anywhere_returns_none(monkeypatch):
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: ([], []))
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda name, website=None: ([], []))
    monkeypatch.setattr("app.services.search_service.search_configured", lambda: True)
    monkeypatch.setattr("app.services.search_service.search_web", lambda q, **k: [])
    assert vr.collect_vacancy_signals("Nekki", "nekki.com") is None


def test_not_hiring_returns_none(monkeypatch):
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: ([], []))
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda name, website=None: ([], []))
    monkeypatch.setattr("app.services.search_service.search_configured", lambda: True)
    monkeypatch.setattr("app.services.search_service.search_web", lambda q, **k: _hits("https://nekki.com/about"))
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda prompt: {"is_hiring": False, "open_roles": [], "summary": ""},
    )
    assert vr.collect_vacancy_signals("Nekki", "nekki.com") is None


def test_is_hiring_but_empty_roles_returns_none(monkeypatch):
    """#9: is_hiring=True with no concrete role is ambiguous — must not be persisted."""
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: (["[careers] we are hiring! (x)"], ["x"]))
    monkeypatch.setattr(
        "app.services.llm_gateway.complete_prompt_json_object",
        lambda prompt: {"is_hiring": True, "open_roles": [], "summary": "hiring, no titles"},
    )
    assert vr.collect_vacancy_signals("Nekki", "nekki.com") is None


def test_boilerplate_careers_page_does_not_mask_real_ats_board(monkeypatch):
    """#10: a careers page with text but no concrete roles must not short-circuit the ATS stage."""
    monkeypatch.setattr(vr, "_corpus_from_careers_page", lambda website: (["[careers] Join our journey! Culture, values. (c)"], ["c"]))
    monkeypatch.setattr(vr, "_corpus_from_ats_patterns", lambda name, website=None: (["[Ashby] Senior Unity Developer — Limassol (a)"], ["a"]))

    def _extract(prompt):
        # careers corpus -> no roles; ATS corpus -> a real role
        if "Ashby" in prompt:
            return {"is_hiring": True, "open_roles": [{"role": "Senior Unity Developer"}], "summary": "hiring"}
        return {"is_hiring": False, "open_roles": [], "summary": ""}

    monkeypatch.setattr("app.services.llm_gateway.complete_prompt_json_object", _extract)
    out = vr.collect_vacancy_signals("Nekki", "nekki.com")
    assert out is not None and out["open_roles"][0]["role"] == "Senior Unity Developer"


# --- Slug-collision guard (#4) ---

def test_board_identifies_company_by_domain():
    assert vr._board_identifies_company("... apply at jobs.nekki.com ...", "Nekki", "https://nekki.com")


def test_board_identifies_company_by_long_distinctive_token():
    assert vr._board_identifies_company("Joyteractive is hiring", "Joyteractive", None)


def test_board_rejects_unrelated_common_slug_collision():
    # 'Match' -> distinctive {'match'} is short (<6) and no domain match -> unrelated board dropped.
    assert not vr._board_identifies_company("Acme Corp careers — Product Manager", "Match", None)


def test_ats_stage_skipped_for_all_generic_name(monkeypatch):
    called = {"fetch": 0}
    monkeypatch.setattr(vr, "_fetch_raw", lambda url: called.__setitem__("fetch", called["fetch"] + 1) or "")
    parts, urls = vr._corpus_from_ats_patterns("The Game Studio", None)
    assert parts == [] and urls == [] and called["fetch"] == 0


def test_ats_stage_drops_colliding_board(monkeypatch):
    # Ashby returns a real board for the guessed slug, but its content is another company's —
    # _board_identifies_company fails, so no corpus is produced.
    import json as _json
    monkeypatch.setattr(vr, "_fetch_raw", lambda url: _json.dumps({"jobs": [{"title": "Product Manager", "location": "Berlin"}], "org": "Acme"}))
    monkeypatch.setattr("app.services.company_source_extractor._extract_page_text", lambda url: "")
    parts, urls = vr._corpus_from_ats_patterns("Match", None)
    assert parts == [] and urls == []


def test_empty_company_name_returns_none():
    assert vr.collect_vacancy_signals("", "nekki.com") is None


def test_ashby_jobs_parsed_from_json(monkeypatch):
    import json as _json

    class _Resp:
        status_code = 200
        text = _json.dumps({"jobs": [
            {"title": "QA Engineer", "location": "Warsaw"},
            {"title": "", "location": "Nowhere"},  # blank title filtered out
        ]})

        def json(self):
            return _json.loads(self.text)

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())
    jobs = vr._ashby_jobs("Joyteractive")
    assert jobs == [{"title": "QA Engineer", "location": "Warsaw"}]


def test_ashby_jobs_empty_on_non_200(monkeypatch):
    class _Resp:
        status_code = 404
        text = ""

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())
    assert vr._ashby_jobs("nonexistent-co") == []


def test_ashby_jobs_empty_on_network_error(monkeypatch):
    def _raise(*a, **k):
        raise ConnectionError("no route to host")

    monkeypatch.setattr("httpx.get", _raise)
    assert vr._ashby_jobs("nekki") == []
