from datetime import datetime

from sqlalchemy.orm import Session

from app.models.contact import Contact


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


def list_contacts_by_run(db: Session, run_id: int) -> list[Contact]:
    return (
        db.query(Contact)
        .filter(Contact.run_id == run_id)
        .order_by(Contact.id.asc())
        .all()
    )


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


def delete_contacts_by_run(db: Session, run_id: int) -> int:
    query = db.query(Contact).filter(Contact.run_id == run_id)
    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    return count


def bulk_create_contacts(db: Session, contacts_data: list[dict]) -> list[Contact]:
    contacts = [Contact(**item) for item in contacts_data]
    db.add_all(contacts)
    db.commit()

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
