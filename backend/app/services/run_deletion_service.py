"""Hard-delete a run and all rows that reference it (FK-safe order)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.asset_packet import AssetPacket
from app.models.contact import Contact
from app.models.email_attachment import EmailAttachment
from app.models.email_draft import EmailDraft
from app.models.email_event import EmailEvent
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread
from app.models.follow_up_task import FollowUpTask
from app.models.reminder import Reminder
from app.models.reply_draft import ReplyDraft
from app.models.research_task import ResearchTask
from app.models.run import Run
from app.models.step import Step


def delete_run_cascade(db: Session, run_id: int, *, commit: bool = True) -> bool:
    """
    Remove a run and dependent rows. Returns False if the run does not exist.

    Order respects foreign keys (SQLite may not enforce ON DELETE CASCADE).
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return False

    db.query(AssetPacket).filter(AssetPacket.run_id == run_id).delete(synchronize_session=False)
    db.query(Reminder).filter(Reminder.run_id == run_id).delete(synchronize_session=False)
    db.query(FollowUpTask).filter(FollowUpTask.run_id == run_id).delete(synchronize_session=False)
    db.query(ReplyDraft).filter(ReplyDraft.run_id == run_id).delete(synchronize_session=False)

    msg_subq = db.query(EmailMessage.id).filter(EmailMessage.run_id == run_id)
    db.query(EmailAttachment).filter(EmailAttachment.message_id.in_(msg_subq)).delete(
        synchronize_session=False,
    )
    db.query(EmailMessage).filter(EmailMessage.run_id == run_id).delete(synchronize_session=False)

    db.query(ResearchTask).filter(ResearchTask.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailEvent).filter(EmailEvent.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailThread).filter(EmailThread.run_id == run_id).delete(synchronize_session=False)
    db.query(EmailDraft).filter(EmailDraft.run_id == run_id).delete(synchronize_session=False)
    db.query(Contact).filter(Contact.run_id == run_id).delete(synchronize_session=False)
    db.query(Step).filter(Step.run_id == run_id).delete(synchronize_session=False)

    db.query(Run).filter(Run.id == run_id).delete(synchronize_session=False)

    if commit:
        db.commit()
    else:
        db.flush()

    return True
