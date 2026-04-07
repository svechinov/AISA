"""Hard-delete a run and all rows that reference it (FK-safe order)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_CONTACT_SOURCE
from app.models.asset_packet import AssetPacket
from app.models.asset_packet_asset import AssetPacketAsset
from app.models.contact import Contact
from app.models.contact_personalization import ContactPersonalization, ContactPersonalizationFact
from app.models.entity_json_kv import EntityJsonKV
from app.models.email_attachment import EmailAttachment
from app.models.email_draft import EmailDraft
from app.models.email_draft_asset import EmailDraftAsset
from app.models.email_event import EmailEvent
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread
from app.models.follow_up_task import FollowUpTask
from app.models.reminder import Reminder
from app.models.reply_draft import ReplyDraft
from app.models.reply_draft_asset import ReplyDraftAsset
from app.models.research_task import ResearchTask
from app.models.run import Run
from app.models.run_company import RunCompany
from app.models.run_setup import RunSetup
from app.models.step import Step


def delete_contacts_cascade(db: Session, contact_ids: list[int], *, commit: bool = True) -> int:
    """
    Remove contacts and dependent rows (same FK order as run deletion, scoped by contact_id).

    Returns the number of contacts deleted (0 if contact_ids is empty or none exist).
    """
    if not contact_ids:
        return 0

    existing = [r[0] for r in db.query(Contact.id).filter(Contact.id.in_(contact_ids)).all()]
    if not existing:
        return 0

    packet_ids = [
        r[0] for r in db.query(AssetPacket.id).filter(AssetPacket.contact_id.in_(existing)).all()
    ]
    if packet_ids:
        db.query(AssetPacketAsset).filter(AssetPacketAsset.packet_id.in_(packet_ids)).delete(
            synchronize_session=False,
        )
    db.query(AssetPacket).filter(AssetPacket.contact_id.in_(existing)).delete(
        synchronize_session=False,
    )
    db.query(Reminder).filter(Reminder.contact_id.in_(existing)).delete(synchronize_session=False)
    db.query(FollowUpTask).filter(FollowUpTask.contact_id.in_(existing)).delete(
        synchronize_session=False,
    )

    ed_ids = [r[0] for r in db.query(EmailDraft.id).filter(EmailDraft.contact_id.in_(existing)).all()]
    if ed_ids:
        db.query(EmailDraftAsset).filter(EmailDraftAsset.email_draft_id.in_(ed_ids)).delete(
            synchronize_session=False,
        )
    rd_ids = [r[0] for r in db.query(ReplyDraft.id).filter(ReplyDraft.contact_id.in_(existing)).all()]
    if rd_ids:
        db.query(ReplyDraftAsset).filter(ReplyDraftAsset.reply_draft_id.in_(rd_ids)).delete(
            synchronize_session=False,
        )

    db.query(ReplyDraft).filter(ReplyDraft.contact_id.in_(existing)).delete(synchronize_session=False)

    msg_subq = db.query(EmailMessage.id).filter(EmailMessage.contact_id.in_(existing))
    db.query(EmailAttachment).filter(EmailAttachment.message_id.in_(msg_subq)).delete(
        synchronize_session=False,
    )
    db.query(EmailMessage).filter(EmailMessage.contact_id.in_(existing)).delete(
        synchronize_session=False,
    )

    db.query(ResearchTask).filter(ResearchTask.contact_id.in_(existing)).delete(
        synchronize_session=False,
    )
    db.query(EmailEvent).filter(EmailEvent.contact_id.in_(existing)).delete(synchronize_session=False)
    db.query(EmailThread).filter(EmailThread.contact_id.in_(existing)).delete(synchronize_session=False)
    db.query(EmailDraft).filter(EmailDraft.contact_id.in_(existing)).delete(synchronize_session=False)

    db.query(EntityJsonKV).filter(
        EntityJsonKV.scope == SCOPE_CONTACT_SOURCE,
        EntityJsonKV.entity_id.in_(existing),
    ).delete(synchronize_session=False)

    db.query(ContactPersonalizationFact).filter(
        ContactPersonalizationFact.contact_id.in_(existing),
    ).delete(synchronize_session=False)
    db.query(ContactPersonalization).filter(ContactPersonalization.contact_id.in_(existing)).delete(
        synchronize_session=False,
    )

    db.query(Contact).filter(Contact.id.in_(existing)).delete(synchronize_session=False)

    if commit:
        db.commit()
    else:
        db.flush()

    return len(existing)


def delete_run_cascade(db: Session, run_id: int, *, commit: bool = True) -> bool:
    """
    Remove a run and dependent rows. Returns False if the run does not exist.

    Order respects foreign keys (SQLite may not enforce ON DELETE CASCADE).
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return False

    packet_ids = [r[0] for r in db.query(AssetPacket.id).filter(AssetPacket.run_id == run_id).all()]
    if packet_ids:
        db.query(AssetPacketAsset).filter(AssetPacketAsset.packet_id.in_(packet_ids)).delete(
            synchronize_session=False,
        )
    db.query(AssetPacket).filter(AssetPacket.run_id == run_id).delete(synchronize_session=False)
    db.query(Reminder).filter(Reminder.run_id == run_id).delete(synchronize_session=False)
    db.query(FollowUpTask).filter(FollowUpTask.run_id == run_id).delete(synchronize_session=False)

    ed_ids = [r[0] for r in db.query(EmailDraft.id).filter(EmailDraft.run_id == run_id).all()]
    if ed_ids:
        db.query(EmailDraftAsset).filter(EmailDraftAsset.email_draft_id.in_(ed_ids)).delete(
            synchronize_session=False,
        )
    rd_ids = [r[0] for r in db.query(ReplyDraft.id).filter(ReplyDraft.run_id == run_id).all()]
    if rd_ids:
        db.query(ReplyDraftAsset).filter(ReplyDraftAsset.reply_draft_id.in_(rd_ids)).delete(
            synchronize_session=False,
        )

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
    db.query(RunCompany).filter(RunCompany.run_id == run_id).delete(synchronize_session=False)
    db.query(Step).filter(Step.run_id == run_id).delete(synchronize_session=False)
    db.query(RunSetup).filter(RunSetup.run_id == run_id).delete(synchronize_session=False)

    db.query(Run).filter(Run.id == run_id).delete(synchronize_session=False)

    if commit:
        db.commit()
    else:
        db.flush()

    return True
