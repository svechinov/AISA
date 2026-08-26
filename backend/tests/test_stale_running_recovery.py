"""DB-backed tests for the stale-'running' recovery (backlog B-141): run_workflow executes
synchronously inside POST /runs/{id}/start, so a process restart mid-run (deploy/OOM/proxy
timeout) never reaches the except block that would mark the run/step 'failed' — it is left
'running' forever. Requires the ai_biz_os_realrun.db snapshot (see conftest.py).
"""

from datetime import datetime, timedelta

from app.models.project import Project
from app.models.run import Run
from app.models.step import Step
from app.repositories.run_repo import reset_stale_running_runs
from app.repositories.step_repo import mark_step_running, reset_stale_running_steps


def _make_run(db, suffix: str) -> Run:
    project = Project(name=f"stale-running-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"stale-running-run-{suffix}")
    db.add(run)
    db.commit()
    return run


def test_mark_step_running_resets_finished_at(db):
    """Re-running a previously-finished step must clear the old finished_at — otherwise the row
    ends up with status='running' and a stale finished_at, an impossible combination."""
    run = _make_run(db, "reset-finished-at")
    step = Step(
        run_id=run.id, step_name="collect_companies", status="completed",
        finished_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add(step)
    db.commit()

    updated = mark_step_running(db, step, {})

    assert updated.status == "running"
    assert updated.finished_at is None


def test_reset_stale_running_steps_fails_running_and_leaves_others_alone(db):
    run = _make_run(db, "stale-steps")
    running = Step(run_id=run.id, step_name="collect_companies", status="running")
    pending = Step(run_id=run.id, step_name="find_contacts", status="pending")
    completed = Step(
        run_id=run.id, step_name="generate_emails", status="completed", finished_at=datetime.utcnow(),
    )
    db.add_all([running, pending, completed])
    db.commit()

    n = reset_stale_running_steps(db)
    assert n >= 1

    db.refresh(running)
    db.refresh(pending)
    db.refresh(completed)

    assert running.status == "failed"
    assert running.error_text == "прервано рестартом процесса (recovery при старте)"
    assert running.finished_at is not None
    assert pending.status == "pending"
    assert completed.status == "completed"


def test_reset_stale_running_runs_fails_running_and_leaves_others_alone(db):
    running = _make_run(db, "stale-run-running")
    running.status = "running"
    db.add(running)
    needs_review = _make_run(db, "stale-run-needs-review")
    needs_review.status = "needs_review"
    db.add(needs_review)
    db.commit()

    n = reset_stale_running_runs(db)
    assert n >= 1

    db.refresh(running)
    db.refresh(needs_review)

    assert running.status == "failed"
    assert running.finished_at is not None
    assert needs_review.status == "needs_review"
    assert needs_review.finished_at is None
