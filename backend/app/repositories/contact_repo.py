from datetime import datetime

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.utils.contact_identity import contact_identity_key_from_row


def create_contact(
    db: Session,
    run_id: int,
    company: str | None,
    website: str | None,
    name: str | None,
    role: str | None,
    email: str | None,
    linkedin: str | None = None,
    status: str = "new",
    confidence: str | None = None,
    source_json: dict | None = None,
    review_status: str = "pending",
    review_notes: str | None = None,
) -> Contact:
    contact = Contact(
        run_id=run_id,
        company=company,
        website=website,
        name=name,
        role=role,
        email=email,
        linkedin=linkedin,
        status=status,
        confidence=confidence,
        source_json=source_json or {},
        review_status=review_status,
        review_notes=review_notes,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


_REVIEW_RANK = {"pending": 0, "rejected": 1, "approved": 2, "edited": 2}


def list_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    """One visible row per normalized email; legacy duplicates collapse (draft / review / id tie-break)."""
    rows = (
        db.query(Contact)
        .filter(Contact.run_id == run_id)
        .order_by(Contact.id.asc())
        .all()
    )
    if not rows:
        return []

    ids = [c.id for c in rows]
    draft_contact_ids = {
        r[0]
        for r in db.query(EmailDraft.contact_id)
        .filter(EmailDraft.contact_id.in_(ids))
        .distinct()
        .all()
    }

    no_email_groups: dict[str, list[Contact]] = {}
    no_email_fallback: list[Contact] = []
    by_email: dict[str, list[Contact]] = {}
    for c in rows:
        em = (c.email or "").strip().lower()
        if not em or "@" not in em:
            ik = contact_identity_key_from_row(
                name=c.name,
                company=c.company,
                website=c.website,
            )
            if ik:
                no_email_groups.setdefault(ik, []).append(c)
            else:
                no_email_fallback.append(c)
            continue
        by_email.setdefault(em, []).append(c)

    identities_with_email: set[str] = set()
    for group in by_email.values():
        for c in group:
            ik = contact_identity_key_from_row(
                name=c.name,
                company=c.company,
                website=c.website,
            )
            if ik:
                identities_with_email.add(ik)

    def pick_canonical(group: list[Contact]) -> Contact:
        if len(group) == 1:
            return group[0]
        with_draft = [c for c in group if c.id in draft_contact_ids]
        if with_draft:
            return min(with_draft, key=lambda c: c.id)
        best = group[0]
        best_r = _REVIEW_RANK.get(best.review_status or "pending", 0)
        for c in group[1:]:
            cr = _REVIEW_RANK.get(c.review_status or "pending", 0)
            if cr > best_r or (cr == best_r and c.id < best.id):
                best, best_r = c, cr
        return best

    out: list[Contact] = list(no_email_fallback)
    for ik, group in no_email_groups.items():
        if ik in identities_with_email:
            continue
        out.append(pick_canonical(group))
    for group in by_email.values():
        out.append(pick_canonical(group))
    out.sort(key=lambda c: c.id)
    return out


def list_valid_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    return (
        db.query(Contact)
        .filter(Contact.run_id == run_id, Contact.status == "valid")
        .order_by(Contact.id.asc())
        .all()
    )


def list_approved_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    return (
        db.query(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.status == "valid",
            Contact.review_status == "approved",
        )
        .order_by(Contact.id.asc())
        .all()
    )


def list_sendable_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    return (
        db.query(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.status == "valid",
            Contact.review_status.in_(["approved", "edited"]),
        )
        .order_by(Contact.id.asc())
        .all()
    )


def list_approved_replacement_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    contacts = (
        db.query(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.status == "valid",
            Contact.review_status.in_(["approved", "edited"]),
        )
        .order_by(Contact.id.asc())
        .all()
    )

    result: list[Contact] = []
    for contact in contacts:
        source_json = contact.source_json or {}
        if source_json.get("source") == "replacement_search":
            result.append(contact)

    return result


def get_contact(db: Session, contact_id: int) -> Contact | None:
    return db.query(Contact).filter(Contact.id == contact_id).first()


def find_replacement_contact_for_source(
    db: Session,
    run_id: int,
    source_contact_id: int,
) -> Contact | None:
    contacts = (
        db.query(Contact)
        .filter(Contact.run_id == run_id)
        .order_by(Contact.id.asc())
        .all()
    )

    for contact in contacts:
        source_json = contact.source_json or {}
        if source_json.get("replaces_contact_id") == source_contact_id:
            return contact

    return None


def create_replacement_contact(
    db: Session,
    run_id: int,
    source_contact_id: int | None,
    research_task_id: int,
    company: str | None,
    website: str | None,
    name: str | None,
    role: str | None,
    email: str | None,
    linkedin: str | None = None,
    confidence: str | None = None,
) -> Contact:
    """Always a new row; never updates the dead-mailbox source contact."""
    contact = Contact(
        run_id=run_id,
        company=company,
        website=website,
        name=name,
        role=role,
        email=email,
        linkedin=linkedin,
        status="valid",
        confidence=confidence,
        review_status="pending",
        review_notes=None,
        email_health="unknown",
        source_json={
            "source": "replacement_search",
            "replaces_contact_id": source_contact_id,
            "research_task_id": research_task_id,
        },
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def mark_contact_email_health(
    db: Session,
    contact: Contact,
    email_health: str,
) -> Contact:
    contact.email_health = email_health
    contact.last_contact_event_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def mark_contact_replied(db: Session, contact: Contact) -> Contact:
    contact.last_contact_event_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def delete_contacts_by_run(db: Session, run_id: int, *, commit: bool = True) -> int:
    query = db.query(Contact).filter(Contact.run_id == run_id)
    count = query.count()
    query.delete(synchronize_session=False)
    if commit:
        db.commit()
    else:
        db.flush()
    return count


def bulk_create_contacts(
    db: Session,
    contacts_data: list[dict],
    *,
    commit: bool = True,
) -> list[Contact]:
    contacts = [Contact(**item) for item in contacts_data]
    db.add_all(contacts)
    if commit:
        db.commit()
        for contact in contacts:
            db.refresh(contact)
    else:
        db.flush()
        for contact in contacts:
            db.refresh(contact)

    return contacts


def update_contact_review(
    db: Session,
    contact: Contact,
    review_status: str,
    review_notes: str | None = None,
) -> Contact:
    contact.review_status = review_status
    contact.review_notes = review_notes
    contact.reviewed_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact_fields(
    db: Session,
    contact: Contact,
    company: str | None = None,
    website: str | None = None,
    name: str | None = None,
    role: str | None = None,
    email: str | None = None,
    linkedin: str | None = None,
    confidence: str | None = None,
    review_notes: str | None = None,
) -> Contact:
    if company is not None:
        contact.company = company
    if website is not None:
        contact.website = website
    if name is not None:
        contact.name = name
    if role is not None:
        contact.role = role
    if email is not None:
        contact.email = email
    if linkedin is not None:
        contact.linkedin = linkedin
    if confidence is not None:
        contact.confidence = confidence
    if review_notes is not None:
        contact.review_notes = review_notes

    contact.review_status = "edited"
    contact.reviewed_at = datetime.utcnow()

    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def list_contacts_raw_by_run(db: Session, run_id: int) -> list[Contact]:
    """All contact rows for the run (no collapse by email — used for Contact analyzer)."""
    return (
        db.query(Contact).filter(Contact.run_id == run_id).order_by(Contact.id.asc()).all()
    )


def apply_gmail_history_to_contacts(
    db: Session,
    contacts: list[Contact],
    *,
    status: str,
    checked_at: datetime,
) -> None:
    for c in contacts:
        c.gmail_history_status = status
        c.gmail_history_checked_at = checked_at
        db.add(c)
    db.commit()


def apply_gmail_inbox_imported_at(
    db: Session,
    contacts: list[Contact],
    *,
    imported_at: datetime,
) -> None:
    for c in contacts:
        c.gmail_inbox_imported_at = imported_at
        db.add(c)
    db.commit()
