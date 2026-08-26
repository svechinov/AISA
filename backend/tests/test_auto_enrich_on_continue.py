"""Regression for the audit 2026-06-16 #4 fix (orchestrator.py continue_workflow_after_review):
enrich_crm_data must run automatically between review and generation, or the email pipeline grounds
its hook/problem slots in an empty osint_dossier/person_osint. The fix landed with zero test
coverage — AUTO_ENRICH_DISABLED and continue_workflow_after_review appear in no test file — so a
silent revert to manual-only advancement would pass CI unnoticed. 0 tokens: STEP_HANDLERS is never
reached, execute_step is stubbed at the orchestrator module level (same idiom as
test_program_matcher.py's monkeypatch.setattr(pm, "complete_prompt_json_object", fake))."""

import app.services.orchestrator as orch
from app.models.project import Project
from app.models.run import Run


def _make_needs_review_run(db, *, suffix: str) -> Run:
    project = Project(name=f"auto-enrich-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="generic_outreach", name=f"run-{suffix}")
    db.add(run)
    db.commit()
    orch.update_run_status(db, run, "needs_review")
    return run


def _stub_execute_step(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(orch, "execute_step", lambda db, run_id, step_name: calls.append(step_name))
    return calls


def test_continue_runs_enrich_before_generation(monkeypatch, fresh_db):
    calls = _stub_execute_step(monkeypatch)
    run = _make_needs_review_run(fresh_db, suffix="default")

    orch.continue_workflow_after_review(fresh_db, run.id)

    assert "enrich_crm_data" in calls
    assert calls.index("enrich_crm_data") < calls.index("generate_emails")


def test_continue_skips_enrich_if_already_completed(monkeypatch, fresh_db):
    """Idempotency: a re-run of /continue must not redo a completed enrich step."""
    from app.repositories.step_repo import create_step, mark_step_completed

    calls = _stub_execute_step(monkeypatch)
    run = _make_needs_review_run(fresh_db, suffix="already-done")
    step = create_step(fresh_db, run.id, "enrich_crm_data", {})
    mark_step_completed(fresh_db, step, {})

    orch.continue_workflow_after_review(fresh_db, run.id)

    assert "enrich_crm_data" not in calls
    assert "generate_emails" in calls


def test_auto_enrich_disabled_env_skips_it(monkeypatch, fresh_db):
    monkeypatch.setenv("AUTO_ENRICH_DISABLED", "1")
    calls = _stub_execute_step(monkeypatch)
    run = _make_needs_review_run(fresh_db, suffix="disabled")

    orch.continue_workflow_after_review(fresh_db, run.id)

    assert "enrich_crm_data" not in calls
    assert "generate_emails" in calls
