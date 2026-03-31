from sqlalchemy.orm import Session

from app.models.contact import Contact


def _norm_email(contact: dict) -> str:
    return (contact.get("email") or "").strip().lower()


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
    for row in existing:
        em = (row.email or "").strip().lower()
        if em and "@" in em and em not in by_email:
            by_email[em] = row

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

    for contact in valid_contacts:
        upsert(contact, "valid")
    for contact in invalid_contacts:
        upsert(contact, "invalid")

    if commit:
        db.commit()
    else:
        db.flush()

    return {
        "saved_contacts": new_count,
        "valid_count": len(valid_contacts),
        "invalid_count": len(invalid_contacts),
    }
