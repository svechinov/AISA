"""B-264: cross-run company exclusion registry.

"Not our segment" used to live only inside one run (run_companies.ai_fit_status='incorrect'), so
the next Apollo sweep with the same filters collected the same competitor / job board / PSL-locked
subsidiary again and paid for research on it twice (US wave 1: 10 of 24 companies).
"""

from types import SimpleNamespace

import app.workers.research_worker as rw
from app.models.excluded_company import EXCLUDE_REASON_COMPETITOR, EXCLUDE_REASON_JOB_BOARD
from app.repositories.excluded_company_repo import (
    add_excluded_company,
    company_name_key,
    delete_excluded_company,
    filter_excluded_companies,
    is_company_excluded,
)


# --- Match keys ---------------------------------------------------------------------------------

def test_name_key_is_case_and_punctuation_insensitive():
    assert company_name_key("8Bit Recruitment Ltd.") == company_name_key("8bit  recruitment ltd")
    assert company_name_key("") is None
    assert company_name_key(None) is None


def test_name_key_keeps_corporate_suffix():
    # "Sunday Games" and "Sunday Games Studio" can be different studios — never merge them.
    assert company_name_key("Sunday Games") != company_name_key("Sunday Games Studio")


# --- Registry round-trip ------------------------------------------------------------------------

def test_add_and_match_by_domain(db):
    row = add_excluded_company(
        db, name="8Bit Unique Test Agency", website="https://www.8bit-unique-test.io/about",
        reason=EXCLUDE_REASON_COMPETITOR, note="конкурент",
    )
    assert row is not None and row.domain == "8bit-unique-test.io"
    try:
        # Same company, different page and a differently-spelled name → still excluded (by domain).
        hit = is_company_excluded(db, "8bit unique test agency GmbH", "http://8bit-unique-test.io/careers")
        assert hit is not None and hit.id == row.id
    finally:
        delete_excluded_company(db, row.id)


def test_add_and_match_by_name_when_website_missing(db):
    row = add_excluded_company(db, name="Zzz Unique Job Board B264", reason=EXCLUDE_REASON_JOB_BOARD)
    assert row is not None and row.domain is None
    try:
        assert is_company_excluded(db, "ZZZ  unique job board b264", None) is not None
        assert is_company_excluded(db, "Some Other Studio B264", None) is None
    finally:
        delete_excluded_company(db, row.id)


def test_add_is_idempotent_and_backfills_domain(db):
    first = add_excluded_company(db, name="Idem Unique Studio B264")
    try:
        second = add_excluded_company(db, name="Idem Unique Studio B264", website="https://idem-unique-b264.com")
        assert second is not None and second.id == first.id
        assert second.domain == "idem-unique-b264.com"  # identity filled in on the second sighting
    finally:
        delete_excluded_company(db, first.id)


def test_add_needs_a_name_or_a_website(db):
    assert add_excluded_company(db, name="   ", website=None) is None


def test_filter_splits_kept_and_dropped(db):
    row = add_excluded_company(db, name="Dropme Unique B264", website="https://dropme-unique-b264.com")
    try:
        companies = [
            {"name": "Dropme Unique B264", "website": "https://dropme-unique-b264.com"},
            {"name": "Keepme Unique B264", "website": "https://keepme-unique-b264.com"},
        ]
        kept, dropped = filter_excluded_companies(db, companies)
        assert [c["name"] for c in kept] == ["Keepme Unique B264"]
        assert len(dropped) == 1 and dropped[0][1].id == row.id
    finally:
        delete_excluded_company(db, row.id)


# --- Wiring into collect_companies ---------------------------------------------------------------

class _Run:
    workflow_name = "generic_outreach"
    run_setup = None


def _patch_worker(monkeypatch):
    monkeypatch.setattr(rw, "get_run", lambda db, rid: _Run())
    monkeypatch.setattr(rw, "get_effective_rules_from_run", lambda *a, **k: [])
    monkeypatch.setattr(rw, "build_collect_companies_task", lambda run, continuation=False: "task")
    monkeypatch.setattr(rw, "collect_companies_annotate_llm_flags", lambda raw, *, run_id: raw)
    monkeypatch.setattr(rw, "push_human_ui_activity", lambda *a, **k: None)


def test_apollo_companies_filtered_by_registry(monkeypatch):
    _patch_worker(monkeypatch)
    monkeypatch.setattr(rw, "apollo_configured", lambda: True)
    monkeypatch.setattr(
        rw, "try_collect_companies_via_apollo",
        lambda db, rid, run, *, continuation: {"companies": [{"name": "Banned"}, {"name": "Fresh"}]},
    )
    monkeypatch.setattr(
        rw, "filter_excluded_companies",
        lambda db, companies, run_id=None: ([c for c in companies if c["name"] != "Banned"], [(companies[0], SimpleNamespace(reason="competitor"))]),
    )
    monkeypatch.setattr(rw, "get_tavily_client", lambda: (_ for _ in ()).throw(AssertionError("Tavily called")))

    out = rw.collect_companies(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert [c["name"] for c in out["companies"]] == ["Fresh"]


def test_llm_companies_filtered_by_registry(monkeypatch):
    _patch_worker(monkeypatch)
    monkeypatch.setattr(rw, "apollo_configured", lambda: False)
    monkeypatch.setattr(rw, "list_run_companies_sparse", lambda db, rid: [])
    monkeypatch.setattr(rw, "get_tavily_client", lambda: None)
    monkeypatch.setattr(rw, "build_prompt", lambda **k: "prompt")
    monkeypatch.setattr(rw, "generate_json", lambda *a, **k: {"companies": [{"name": "Banned"}, {"name": "Fresh"}]})
    monkeypatch.setattr(
        rw, "filter_excluded_companies",
        lambda db, companies, run_id=None: ([c for c in companies if c["name"] != "Banned"], [(companies[0], SimpleNamespace(reason="competitor"))]),
    )

    out = rw.collect_companies(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert [c["name"] for c in out["companies"]] == ["Fresh"]


def test_registry_failure_keeps_companies(monkeypatch):
    # Fail open: the registry saves research spend, it is not a safety gate.
    _patch_worker(monkeypatch)
    monkeypatch.setattr(rw, "apollo_configured", lambda: True)
    monkeypatch.setattr(
        rw, "try_collect_companies_via_apollo",
        lambda db, rid, run, *, continuation: {"companies": [{"name": "Fresh"}]},
    )
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(rw, "filter_excluded_companies", _boom)
    monkeypatch.setattr(rw, "get_tavily_client", lambda: (_ for _ in ()).throw(AssertionError("Tavily called")))

    out = rw.collect_companies(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert [c["name"] for c in out["companies"]] == ["Fresh"]
