from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.services.personalization_service import sync_contact_personalization_row
from app.utils.contact_identity import contact_identity_key_from_row
from app.utils.contact_source_payload import effective_contact_source_json, persist_contact_source


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
    sj = source_json or {}
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
        source_json={},
        review_status=review_status,
        review_notes=review_notes,
    )
    db.add(contact)
    db.flush()
    persist_contact_source(db, contact, sj)
    sync_contact_personalization_row(db, contact)
    db.commit()
    db.refresh(contact)
    return contact


_REVIEW_RANK = {"pending": 0, "rejected": 1, "approved": 2, "edited": 2}


class ContactMinimal(NamedTuple):
    """Scalar columns only — no JSON blobs. Used for GET /contacts/run dedupe + paging without loading full ORM rows."""

    id: int
    run_id: int
    company: str | None
    website: str | None
    name: str | None
    role: str | None
    email: str | None
    linkedin: str | None
    status: str
    confidence: str | None
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    email_health: str
    last_contact_event_at: datetime | None
    gmail_history_status: str | None
    gmail_history_checked_at: datetime | None
    gmail_inbox_imported_at: datetime | None
    created_at: datetime


def _load_contact_minimals_for_run(db: Session, run_id: int) -> list[ContactMinimal]:
    """Single round-trip; does not read source_json / personalization_json."""
    stmt = (
        select(
            Contact.id,
            Contact.run_id,
            Contact.company,
            Contact.website,
            Contact.name,
            Contact.role,
            Contact.email,
            Contact.linkedin,
            Contact.status,
            Contact.confidence,
            Contact.review_status,
            Contact.review_notes,
            Contact.reviewed_at,
            Contact.email_health,
            Contact.last_contact_event_at,
            Contact.gmail_history_status,
            Contact.gmail_history_checked_at,
            Contact.gmail_inbox_imported_at,
            Contact.created_at,
        )
        .where(Contact.run_id == run_id)
        .order_by(Contact.id.asc())
    )
    return [ContactMinimal(*r) for r in db.execute(stmt).all()]


def _dedupe_contact_minimals(
    rows: list[ContactMinimal],
    draft_contact_ids: set[int],
) -> list[ContactMinimal]:
    """Same semantics as list_contacts_by_run (email collapse + no-email identity), on minimal rows."""
    if not rows:
        return []

    no_email_groups: dict[str, list[ContactMinimal]] = {}
    no_email_fallback: list[ContactMinimal] = []
    by_email: dict[str, list[ContactMinimal]] = {}
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

    def pick_canonical(group: list[ContactMinimal]) -> ContactMinimal:
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

    out: list[ContactMinimal] = list(no_email_fallback)
    for ik, group in no_email_groups.items():
        if ik in identities_with_email:
            continue
        out.append(pick_canonical(group))
    for group in by_email.values():
        out.append(pick_canonical(group))
    out.sort(key=lambda c: c.id)
    return out


def dedupe_contact_minimals_for_run(db: Session, run_id: int) -> list[ContactMinimal]:
    """Deduped visible rows for a run — scalar load only; no JSON columns."""
    rows = _load_contact_minimals_for_run(db, run_id)
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
    return _dedupe_contact_minimals(rows, draft_contact_ids)


def hydrate_contacts_for_list_read(db: Session, ordered_ids: list[int]) -> list[Contact]:
    """Load ORM rows (JSON deferred) for ContactRead in ``ordered_ids`` order."""
    if not ordered_ids:
        return []
    q = (
        db.query(Contact)
        .options(defer(Contact.source_json))
        .filter(Contact.id.in_(ordered_ids))
    )
    by_id = {c.id: c for c in q.all()}
    return [by_id[i] for i in ordered_ids if i in by_id]


def list_contacts_by_run(db: Session, run_id: int, *, load_json: bool = True) -> list[Contact]:
    """One visible row per normalized email; legacy duplicates collapse (draft / review / id tie-break).

    When ``load_json`` is False, ``source_json`` and ``personalization_json`` are deferred so the initial
    query does not pull multi‑MB blobs. GET /contacts/run never hydrates them — list payloads use scalars only.
    """
    q = db.query(Contact).filter(Contact.run_id == run_id).order_by(Contact.id.asc())
    if not load_json:
        q = q.options(defer(Contact.source_json))
    rows = q.all()
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
        source_json = effective_contact_source_json(db, contact)
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
        source_json = effective_contact_source_json(db, contact)
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
    sj = {
        "source": "replacement_search",
        "replaces_contact_id": source_contact_id,
        "research_task_id": research_task_id,
    }
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
        source_json={},
    )
    db.add(contact)
    db.flush()
    persist_contact_source(db, contact, sj)
    sync_contact_personalization_row(db, contact)
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
    for c in contacts:
        sync_contact_personalization_row(db, c)
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

    sync_contact_personalization_row(db, contact)
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
