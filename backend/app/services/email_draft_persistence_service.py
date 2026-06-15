import logging

from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import bulk_create_email_drafts, find_draft_by_contact_id

logger = logging.getLogger(__name__)


def matched_program_asset_id(meta: dict | None) -> int | None:
    """Asset id of the matched catalog program (Feature 1). Recorded on the draft (meta) but NOT
    attached to the cold email — the program PDF is sent only as a follow-up after a positive
    reply (decision 12.06); the cold email carries the program summary in the body instead."""
    if not isinstance(meta, dict):
        return None
    mp = meta.get("matched_program")
    if not isinstance(mp, dict):
        return None
    aid = mp.get("asset_id")
    return aid if isinstance(aid, int) else None


def persist_generated_emails(db: Session, run_id: int, step_output: dict) -> dict:
    emails = step_output.get("emails", [])

    rows: list[dict] = []

    for email in emails:
        contact_id = email.get("contact_id")
        if not contact_id:
            continue
        if find_draft_by_contact_id(db, run_id, contact_id):
            continue
        row = {
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
        meta = email.get("generation_meta_json")
        if meta is not None:
            row["generation_meta_json"] = meta
        rows.append(row)

    # Cold drafts carry NO program PDF attachment (the matched program lives in the body summary
    # and is recorded in generation_meta_json/matched_program_json for a post-reply materials send).
    created = bulk_create_email_drafts(db, rows) if rows else []

    return {
        "saved_drafts": len(created),
        "draft_count": len(created),
    }
