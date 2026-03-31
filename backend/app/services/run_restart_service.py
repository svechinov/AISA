"""Re-run setup + validation workflow for an existing run (same brief, fresh steps/contacts)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.asset_packet import AssetPacket
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread
from app.models.follow_up_task import FollowUpTask
from app.models.reminder import Reminder
from app.models.reply_draft import ReplyDraft
from app.models.research_task import ResearchTask
from app.models.email_event import EmailEvent
from app.repositories.contact_repo import delete_contacts_by_run
from app.repositories.email_draft_repo import delete_email_drafts_by_run
from app.repositories.run_repo import get_run
from app.repositories.step_repo import delete_steps_by_run
from app.services.orchestrator import run_workflow


def restart_run_workflow(db: Session, run_id: int):
    """
    Clear run-scoped pipeline data and execute run_workflow again.
    Not allowed for closed runs.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")
    if run.closed_at is not None:
        raise ValueError("Cannot restart a closed run")

    # Order respects typical FKs (children before parents).
    db.query(AssetPacket).filter(AssetPacket.run_id == run_id).delete(synchronize_session=False)
    db.query(Reminder).filter(Reminder.run_id == run_id).delete(synchronize_session=False)
    db.query(FollowUpTask).filter(FollowUpTask.run_id == run_id).delete(synchronize_session=False)
    db.query(ReplyDraft).filter(ReplyDraft.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailMessage).filter(EmailMessage.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailThread).filter(EmailThread.run_id == run_id).delete(synchronize_session=False)
    db.query(ResearchTask).filter(ResearchTask.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailEvent).filter(EmailEvent.run_id == run_id).delete(synchronize_session=False)
    db.commit()

    delete_email_drafts_by_run(db, run_id)
    delete_contacts_by_run(db, run_id)
    delete_steps_by_run(db, run_id)
    db.commit()

    run.master_email = None
    run.master_email_subject = None
    run.master_email_body = None
    run.status = "pending"
    run.finished_at = None
    db.add(run)
    db.commit()
    db.refresh(run)

    run_workflow(db, run_id)
    return get_run(db, run_id)
