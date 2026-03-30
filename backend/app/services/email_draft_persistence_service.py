from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import bulk_create_email_drafts, find_draft_by_contact_id


def persist_generated_emails(db: Session, run_id: int, step_output: dict) -> dict:
    emails = step_output.get("emails", [])

    rows: list[dict] = []

    for email in emails:
        contact_id = email.get("contact_id")
        if not contact_id:
            continue
        if find_draft_by_contact_id(db, run_id, contact_id):
            continue
        rows.append(
            {
                "run_id": run_id,
                "contact_id": contact_id,
                "company": email.get("company"),
                "to_email": email.get("to"),
                "subject": email.get("subject") or "",
                "body": email.get("body") or "",
                "status": "draft",
                "tracking_status": "draft",
                "review_status": "pending",
                "review_notes": None,
            }
        )

    created = bulk_create_email_drafts(db, rows) if rows else []

    return {
        "saved_drafts": len(created),
        "draft_count": len(created),
    }
