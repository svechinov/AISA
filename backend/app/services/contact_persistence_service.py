from sqlalchemy.orm import Session

from app.models.asset_packet import AssetPacket
from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_event import EmailEvent
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread
from app.models.follow_up_task import FollowUpTask
from app.models.reminder import Reminder
from app.models.reply_draft import ReplyDraft
from app.models.research_task import ResearchTask
from app.utils.contact_identity import contact_identity_key_from_dict, contact_identity_key_from_row


def _norm_email(contact: dict) -> str:
    return (contact.get("email") or "").strip().lower()


def _has_usable_email(email: str | None) -> bool:
    em = (email or "").strip().lower()
    return bool(em and "@" in em)


def _contact_has_dependents(db: Session, contact_id: int) -> bool:
    if db.query(EmailDraft.id).filter(EmailDraft.contact_id == contact_id).limit(1).first():
        return True
    if db.query(ReplyDraft.id).filter(ReplyDraft.contact_id == contact_id).limit(1).first():
        return True
    if db.query(EmailThread.id).filter(EmailThread.contact_id == contact_id).limit(1).first():
        return True
    if db.query(EmailMessage.id).filter(EmailMessage.contact_id == contact_id).limit(1).first():
        return True
    if db.query(EmailEvent.id).filter(EmailEvent.contact_id == contact_id).limit(1).first():
        return True
    if db.query(FollowUpTask.id).filter(FollowUpTask.contact_id == contact_id).limit(1).first():
        return True
    if db.query(AssetPacket.id).filter(AssetPacket.contact_id == contact_id).limit(1).first():
        return True
    if db.query(Reminder.id).filter(Reminder.contact_id == contact_id).limit(1).first():
        return True
    if db.query(ResearchTask.id).filter(ResearchTask.contact_id == contact_id).limit(1).first():
        return True
    return False


def _prune_shadow_no_email_contacts(db: Session, run_id: int) -> int:
    """
    Remove no-email rows when the same name+company+website already has a row with email.

    Safe only when the redundant row has no FK children (drafts, threads, etc.).
    """
    rows = db.query(Contact).filter(Contact.run_id == run_id).all()
    ik_with_email: set[str] = set()
    for row in rows:
        if not _has_usable_email(row.email):
            continue
        ik = contact_identity_key_from_row(name=row.name, company=row.company, website=row.website)
        if ik:
            ik_with_email.add(ik)

    deleted = 0
    for row in rows:
        if _has_usable_email(row.email):
            continue
        ik = contact_identity_key_from_row(name=row.name, company=row.company, website=row.website)
        if not ik or ik not in ik_with_email:
            continue
        if _contact_has_dependents(db, row.id):
            continue
        db.delete(row)
        deleted += 1
    return deleted


def persist_validated_contacts(
    db: Session,
    run_id: int,
    step_output: dict,
    *,
    commit: bool = True,
) -> dict:
    """
    Upsert contacts from validate_contacts output by normalized email.

    Preserves existing row id, review_*, email_health, and last_contact_event_at so drafts and
    review state survive additional setup rounds or run restart.
    """
    valid_contacts = step_output.get("valid_contacts", [])
    invalid_contacts = step_output.get("invalid_contacts", [])

    existing = db.query(Contact).filter(Contact.run_id == run_id).all()
    by_email: dict[str, Contact] = {}
    by_no_email_identity: dict[str, Contact] = {}
    for row in existing:
        em = (row.email or "").strip().lower()
        if em and "@" in em and em not in by_email:
            by_email[em] = row
            continue
        ik = contact_identity_key_from_row(
            name=row.name,
            company=row.company,
            website=row.website,
        )
        if ik and ik not in by_no_email_identity:
            by_no_email_identity[ik] = row

    new_count = 0

    def upsert(contact: dict, status: str) -> None:
        nonlocal new_count
        em = _norm_email(contact)
        sj = dict(contact) if isinstance(contact, dict) else {}
        base = {
            "company": contact.get("company"),
            "website": contact.get("website"),
            "name": contact.get("name"),
            "role": contact.get("role"),
            "email": contact.get("email"),
            "linkedin": contact.get("linkedin"),
            "status": status,
            "confidence": contact.get("confidence"),
            "source_json": sj,
        }
        if em and "@" in em:
            hit = by_email.get(em)
            if hit:
                hit.company = base["company"]
                hit.website = base["website"]
                hit.name = base["name"]
                hit.role = base["role"]
                hit.email = base["email"]
                hit.linkedin = base["linkedin"]
                hit.status = status
                hit.confidence = base["confidence"]
                hit.source_json = sj
                db.add(hit)
                return

        ik = contact_identity_key_from_dict(contact)
        if ik:
            hit_ne = by_no_email_identity.get(ik)
            if hit_ne:
                hit_ne.company = base["company"]
                hit_ne.website = base["website"]
                hit_ne.name = base["name"]
                hit_ne.role = base["role"]
                hit_ne.email = base["email"]
                hit_ne.linkedin = base["linkedin"]
                hit_ne.status = status
                hit_ne.confidence = base["confidence"]
                hit_ne.source_json = sj
                db.add(hit_ne)
                return

        row = Contact(
            run_id=run_id,
            company=base["company"],
            website=base["website"],
            name=base["name"],
            role=base["role"],
            email=base["email"],
            linkedin=base["linkedin"],
            status=status,
            confidence=base["confidence"],
            source_json=sj,
            review_status="pending",
            review_notes=None,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        new_count += 1
        if em and "@" in em:
            by_email[em] = row
        elif ik:
            by_no_email_identity[ik] = row

    for contact in valid_contacts:
        upsert(contact, "valid")
    for contact in invalid_contacts:
        upsert(contact, "invalid")

    _prune_shadow_no_email_contacts(db, run_id)

    if commit:
        db.commit()
    else:
        db.flush()

    return {
        "saved_contacts": new_count,
        "valid_count": len(valid_contacts),
        "invalid_count": len(invalid_contacts),
    }
