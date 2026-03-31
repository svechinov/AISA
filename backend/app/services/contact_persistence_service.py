from sqlalchemy.orm import Session

from app.repositories.contact_repo import bulk_create_contacts, delete_contacts_by_run


def persist_validated_contacts(
    db: Session,
    run_id: int,
    step_output: dict,
    *,
    commit: bool = True,
) -> dict:
    valid_contacts = step_output.get("valid_contacts", [])
    invalid_contacts = step_output.get("invalid_contacts", [])

    delete_contacts_by_run(db, run_id, commit=commit)

    rows: list[dict] = []

    for contact in valid_contacts:
        rows.append(
            {
                "run_id": run_id,
                "company": contact.get("company"),
                "website": contact.get("website"),
                "name": contact.get("name"),
                "role": contact.get("role"),
                "email": contact.get("email"),
                "linkedin": contact.get("linkedin"),
                "status": "valid",
                "confidence": contact.get("confidence"),
                "source_json": contact,
                "review_status": "pending",
                "review_notes": None,
            }
        )

    for contact in invalid_contacts:
        rows.append(
            {
                "run_id": run_id,
                "company": contact.get("company"),
                "website": contact.get("website"),
                "name": contact.get("name"),
                "role": contact.get("role"),
                "email": contact.get("email"),
                "linkedin": contact.get("linkedin"),
                "status": "invalid",
                "confidence": contact.get("confidence"),
                "source_json": contact,
                "review_status": "pending",
                "review_notes": None,
            }
        )

    created = bulk_create_contacts(db, rows, commit=commit) if rows else []

    return {
        "saved_contacts": len(created),
        "valid_count": len(valid_contacts),
        "invalid_count": len(invalid_contacts),
    }
