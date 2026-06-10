import logging

from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import bulk_create_email_drafts, find_draft_by_contact_id

logger = logging.getLogger(__name__)


def _matched_program_asset_id(meta: dict | None) -> int | None:
    """Asset id of the matched catalog program (Feature 1) — auto-attached to the new draft."""
    if not isinstance(meta, dict):
        return None
    mp = (meta.get("reasoning") or {}).get("matched_program")
    if not isinstance(mp, dict):
        return None
    aid = mp.get("asset_id")
    return aid if isinstance(aid, int) else None


def _attach_matched_program_assets(db: Session, created: list) -> int:
    from app.models.asset import Asset
    from app.repositories.draft_attachment_repo import replace_email_draft_assets

    attached = 0
    for draft in created:
        aid = _matched_program_asset_id(getattr(draft, "generation_meta_json", None))
        if aid is None:
            continue
        asset = db.get(Asset, aid)
        if not asset or asset.status != "active":
            logger.warning(f"Matched program asset {aid} missing/inactive — draft {draft.id} gets no attachment")
            continue
        replace_email_draft_assets(db, draft.id, [aid])
        attached += 1
    if attached:
        db.commit()
    return attached


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

    created = bulk_create_email_drafts(db, rows) if rows else []
    attached = _attach_matched_program_assets(db, created) if created else 0

    return {
        "saved_drafts": len(created),
        "draft_count": len(created),
        "program_pdfs_attached": attached,
    }
