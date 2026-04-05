"""Re-run the outreach setup loop for an existing run without wiping run-scoped data."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.services.orchestrator import run_workflow


def restart_run_workflow(db: Session, run_id: int):
    """
    Run collect → find → validate again on top of existing data (same brief).

    Uses continuation mode: looser stall/milestone exits so the run can add more companies/contacts,
    not stop as soon as counts look unchanged.

    Does not delete contacts, drafts, steps, tracking rows, asset packets, or master email fields.
    Not allowed for closed runs.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")
    if run.closed_at is not None:
        raise ValueError("Cannot restart a closed run")

    run.status = "pending"
    run.finished_at = None
    db.add(run)
    db.commit()
    db.refresh(run)

    run_workflow(db, run_id, continuation=True)
    return get_run(db, run_id)
