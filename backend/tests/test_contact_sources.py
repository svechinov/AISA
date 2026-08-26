"""Apollo-first discovery in both workers.

collect_companies keeps the honest fallthrough: Apollo wins when it yields companies, otherwise
the Tavily/LLM path runs (the old main behavior dead-ended there).

find_contacts does NOT fall through any more (B-274): with Apollo configured, an empty result means
empty. The LLM does not find contacts, it writes plausible ones — an invented name plus a guessed
address that passes verification on a catch-all domain and reaches a letter as a real
decision-maker. The LLM path stays only for runs with no Apollo key at all.
"""

import app.workers.contacts_worker as cw
import app.workers.research_worker as rw


class _Run:
    workflow_name = "generic_outreach"
    run_setup = None


def _patch_common(monkeypatch, module):
    monkeypatch.setattr(module, "get_run", lambda db, rid: _Run())
    monkeypatch.setattr(module, "get_effective_rules_from_run", lambda *a, **k: [])


def _no_exclusions(monkeypatch):
    """B-264: empty cross-run exclusion registry (these tests are about source selection)."""
    monkeypatch.setattr(rw, "filter_excluded_companies", lambda db, companies, run_id=None: (companies, []))


# --- find_contacts -----------------------------------------------------------

def test_find_contacts_uses_apollo_when_it_returns_contacts(monkeypatch):
    _patch_common(monkeypatch, cw)
    monkeypatch.setattr(cw, "build_find_contacts_task", lambda run: "task")
    monkeypatch.setattr(cw, "apollo_configured", lambda: True)
    monkeypatch.setattr(
        cw, "try_find_contacts_via_apollo",
        lambda db, rid, run, si: {"contacts": [{"company": "Murka", "email": "ceo@murka.com"}]},
    )
    # LLM path must NOT run when Apollo delivered contacts.
    monkeypatch.setattr(cw, "generate_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    out = cw.find_contacts(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out["contacts"][0]["email"] == "ceo@murka.com"


def test_find_contacts_empty_apollo_never_calls_llm(monkeypatch):
    # B-274: empty from a configured Apollo is a real answer, not a reason to generate people.
    _patch_common(monkeypatch, cw)
    monkeypatch.setattr(cw, "build_find_contacts_task", lambda run: "task")
    monkeypatch.setattr(cw, "apollo_configured", lambda: True)
    monkeypatch.setattr(cw, "try_find_contacts_via_apollo", lambda db, rid, run, si: {"contacts": []})
    monkeypatch.setattr(cw, "generate_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    out = cw.find_contacts(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out == {"contacts": []}


def test_find_contacts_apollo_failure_never_calls_llm(monkeypatch):
    # B-274: an Apollo outage must not silently downgrade contact discovery to invention either.
    _patch_common(monkeypatch, cw)
    monkeypatch.setattr(cw, "build_find_contacts_task", lambda run: "task")
    monkeypatch.setattr(cw, "apollo_configured", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("apollo 500")

    monkeypatch.setattr(cw, "try_find_contacts_via_apollo", _boom)
    monkeypatch.setattr(cw, "generate_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    out = cw.find_contacts(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out == {"contacts": []}


def test_find_contacts_skips_apollo_when_unconfigured(monkeypatch):
    _patch_common(monkeypatch, cw)
    monkeypatch.setattr(cw, "build_find_contacts_task", lambda run: "task")
    monkeypatch.setattr(cw, "apollo_configured", lambda: False)
    monkeypatch.setattr(
        cw, "try_find_contacts_via_apollo",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Apollo called though unconfigured")),
    )
    monkeypatch.setattr(cw, "list_run_companies_sparse", lambda db, rid: [])
    monkeypatch.setattr(cw, "build_prompt", lambda **k: "prompt")
    monkeypatch.setattr(cw, "generate_json", lambda *a, **k: {"contacts": []})

    out = cw.find_contacts(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out == {"contacts": []}


def test_find_contacts_llm_fallback_tags_source_llm_generated(monkeypatch):
    """Decision 11.08 (B-445): the ungrounded LLM path must tag every contact "llm_generated" —
    it invents plausible people from the company list rather than finding them — so downstream
    never mistakes it for a found/verified source. Existing "source" (if a caller ever supplies
    one) is not overwritten."""
    _patch_common(monkeypatch, cw)
    monkeypatch.setattr(cw, "build_find_contacts_task", lambda run: "task")
    monkeypatch.setattr(cw, "apollo_configured", lambda: False)
    monkeypatch.setattr(cw, "list_run_companies_sparse", lambda db, rid: [])
    monkeypatch.setattr(cw, "build_prompt", lambda **k: "prompt")
    monkeypatch.setattr(
        cw, "generate_json",
        lambda *a, **k: {
            "contacts": [
                {"company": "Murka", "email": "ceo@murka.com"},
                {"company": "Zurna", "email": "cfo@zurna.com", "source": "already_set"},
            ]
        },
    )

    out = cw.find_contacts(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out["contacts"][0]["source"] == "llm_generated"
    assert out["contacts"][1]["source"] == "already_set"


# --- collect_companies -------------------------------------------------------

def test_collect_companies_uses_apollo_when_it_returns_companies(monkeypatch):
    _patch_common(monkeypatch, rw)
    _no_exclusions(monkeypatch)
    monkeypatch.setattr(rw, "build_collect_companies_task", lambda run, continuation=False: "task")
    monkeypatch.setattr(rw, "apollo_configured", lambda: True)
    monkeypatch.setattr(
        rw, "try_collect_companies_via_apollo",
        lambda db, rid, run, *, continuation: {"companies": [{"name": "Murka", "website": "murka.com"}]},
    )
    monkeypatch.setattr(rw, "collect_companies_annotate_llm_flags", lambda raw, *, run_id: raw)
    # Tavily path must NOT run when Apollo delivered companies.
    monkeypatch.setattr(rw, "get_tavily_client", lambda: (_ for _ in ()).throw(AssertionError("Tavily called")))

    out = rw.collect_companies(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out["companies"][0]["name"] == "Murka"


def test_collect_companies_falls_through_when_apollo_empty(monkeypatch):
    _patch_common(monkeypatch, rw)
    _no_exclusions(monkeypatch)
    monkeypatch.setattr(rw, "build_collect_companies_task", lambda run, continuation=False: "task")
    monkeypatch.setattr(rw, "apollo_configured", lambda: True)
    monkeypatch.setattr(rw, "try_collect_companies_via_apollo", lambda db, rid, run, *, continuation: None)
    monkeypatch.setattr(rw, "list_run_companies_sparse", lambda db, rid: [])
    monkeypatch.setattr(rw, "collect_companies_annotate_llm_flags", lambda raw, *, run_id: raw)
    monkeypatch.setattr(rw, "get_tavily_client", lambda: None)  # no Tavily → LLM-only branch
    monkeypatch.setattr(rw, "build_prompt", lambda **k: "prompt")
    monkeypatch.setattr(rw, "generate_json", lambda *a, **k: {"companies": [{"name": "from-llm"}]})

    out = rw.collect_companies(db=None, run_id=1, workflow_name="generic_outreach", step_input={})
    assert out["companies"][0]["name"] == "from-llm"
