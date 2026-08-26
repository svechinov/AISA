"""B-063 code review finding #2: _sanitize_vacancy_signals_for_prompt must strip ALL provenance
(sources AND summary — summary follows vacancy_radar.EXTRACTION_SCHEMA, which names the source by
design, e.g. "Hiring: senior Unity dev, 2D artist (careers page, LinkedIn)") before vacancy_signals
enters any LLM prompt — otherwise the generator re-leaks exactly the surveillance framing HARD
RULE 10 / decision 7 forbid (incident: Brickworks, 15.07)."""

from app.services.outreach_email_pipeline import _sanitize_vacancy_signals_for_prompt


def test_summary_and_sources_stripped_evidence_url_stripped_per_role():
    signals = {
        "is_hiring": True,
        "open_roles": [
            {"role": "Senior Unity Developer", "seniority": "senior", "location": "Limassol",
             "country": "Cyprus", "evidence_url": "https://nekki.com/careers"},
            {"role": "2D Artist", "seniority": "", "location": "", "country": "",
             "evidence_url": "https://linkedin.com/jobs/123"},
        ],
        "summary": "Hiring: senior Unity dev, 2D artist (careers page, LinkedIn)",
        "sources": ["https://nekki.com/careers", "https://linkedin.com/jobs/123"],
    }

    out = _sanitize_vacancy_signals_for_prompt(signals)

    assert "summary" not in out
    assert "sources" not in out
    assert out["is_hiring"] is True
    assert len(out["open_roles"]) == 2
    for role in out["open_roles"]:
        assert "evidence_url" not in role
    assert out["open_roles"][0]["role"] == "Senior Unity Developer"
    assert out["open_roles"][0]["location"] == "Limassol"
    assert out["open_roles"][0]["country"] == "Cyprus"
    assert out["open_roles"][1]["role"] == "2D Artist"


def test_none_passthrough():
    assert _sanitize_vacancy_signals_for_prompt(None) is None


def test_non_dict_passthrough_unchanged():
    assert _sanitize_vacancy_signals_for_prompt("garbage") == "garbage"  # type: ignore[arg-type]


def test_empty_open_roles_still_strips_summary_and_sources():
    signals = {"is_hiring": False, "open_roles": [], "summary": "", "sources": []}
    out = _sanitize_vacancy_signals_for_prompt(signals)
    assert out == {"is_hiring": False, "open_roles": []}
