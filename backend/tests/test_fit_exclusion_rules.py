"""Fork-transition Phase 1, Task 6: the AI-fit judge's "who counts as a competitor, not a buyer"
rule must be overridable per run via run_setups.fit_exclusion_rules_text. The default text says
"a training/consulting provider when we sell training" as its worked example — for a campaign
whose OWN offer is itself training/consulting-adjacent (NODA12 trek A: selling a facilitation tool
TO training/consulting companies), an LLM reading that example literally could plausibly flag every
target as a same-offer competitor instead of a buyer. Uses fresh_db (Task 2) + the real Run/RunSetup
repo functions, same pattern as test_ai_fit_judge.py — _prompt() reaches into run.notes /
run.run_setup via get_effective_context, so a bare mock object is not enough. 0 tokens: no LLM."""

import app.services.run_company_ai_fit_service as svc
from app.models.run_setup import RunSetup
from app.repositories.project_repo import create_project
from app.repositories.run_repo import create_run, get_run, update_run_prompt_setup


def _make_run(fresh_db, *, fit_exclusion_rules_text=None):
    proj = create_project(fresh_db, name="FitExclusionTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    update_run_prompt_setup(fresh_db, run.id, prompt_setup_text="We sell a facilitation tool for training companies.")
    if fit_exclusion_rules_text is not None:
        row = fresh_db.query(RunSetup).filter(RunSetup.run_id == run.id).first()
        row.fit_exclusion_rules_text = fit_exclusion_rules_text
        fresh_db.commit()
    return get_run(fresh_db, run.id)


def test_default_run_setup_none_uses_builtin_rules_verbatim(fresh_db):
    """A run with no run_setup row at all (never called update_run_prompt_setup)."""
    proj = create_project(fresh_db, name="NoSetupTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    prompt = svc._prompt(run, "Acme Training LLC", "acme-training.example")
    assert svc.DEFAULT_FIT_EXCLUSION_RULES in prompt


def test_empty_fit_exclusion_rules_text_falls_back_to_default(fresh_db):
    run = _make_run(fresh_db, fit_exclusion_rules_text="   ")
    prompt = svc._prompt(run, "Acme Training LLC", "acme-training.example")
    assert svc.DEFAULT_FIT_EXCLUSION_RULES in prompt


def test_custom_fit_exclusion_rules_text_replaces_default(fresh_db):
    custom = "Mark incorrect ONLY when the company sells competing systems-simulation hardware."
    run = _make_run(fresh_db, fit_exclusion_rules_text=custom)
    prompt = svc._prompt(run, "Acme Training LLC", "acme-training.example")
    assert custom in prompt
    assert svc.DEFAULT_FIT_EXCLUSION_RULES not in prompt


def test_prompt_still_carries_offer_and_brief(fresh_db):
    """The exclusion-rule swap must not drop the surrounding prompt assembly (offer block, brief)."""
    run = _make_run(fresh_db)
    prompt = svc._prompt(run, "Acme Training LLC", "acme-training.example")
    assert "Company name: Acme Training LLC" in prompt
    assert "Who we target (campaign brief):" in prompt
    assert "What we SELL" in prompt
