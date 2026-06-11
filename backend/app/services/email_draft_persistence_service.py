import logging

from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import bulk_create_email_drafts, find_draft_by_contact_id

logger = logging.getLogger(__name__)


def _matched_program_asset_id(meta: dict | None) -> int | None:
    """Asset id of the matched catalog program (Feature 1) — auto-attached to the new draft."""
    if not isinstance(meta, dict):
        return None
    mp = meta.get("matched_program")
    if not isinstance(mp, dict):
        return None
    aid = mp.get("asset_id")
    return aid if isinstance(aid, int) else None


def sync_matched_program_attachment(db: Session, draft, meta: dict | None) -> bool:
    """Keep the draft's auto-attached program PDF in line with the (re)generated meta.

    Adds the newly matched program's asset, and removes the PREVIOUS program's asset when the
    match changed or disappeared (so a regenerated email never ships a stale brochure). Manual
    attachments are preserved — only the old matched asset is touched. Call BEFORE the new meta
    is applied to the draft (the old match is read from draft.matched_program_json).
    Returns True if attachments changed.
    """
    from app.models.asset import Asset
    from app.repositories.draft_attachment_repo import (
        list_asset_ids_for_email_draft,
        replace_email_draft_assets,
    )

    new_aid = _matched_program_asset_id(meta)
    old_mp = getattr(draft, "matched_program_json", None)
    old_aid = old_mp.get("asset_id") if isinstance(old_mp, dict) else None

    current = list_asset_ids_for_email_draft(db, draft.id)
    desired = list(current)
    if isinstance(old_aid, int) and old_aid != new_aid and old_aid in desired:
        desired = [a for a in desired if a != old_aid]
    if new_aid is not None and new_aid not in desired:
        asset = db.get(Asset, new_aid)
        if asset and asset.status == "active":
            desired = desired + [new_aid]
        else:
            logger.warning(f"Matched program asset {new_aid} missing/inactive — draft {draft.id} gets no attachment")
    if desired == current:
        return False
    replace_email_draft_assets(db, draft.id, desired)
    return True


def _attach_matched_program_assets(db: Session, created: list) -> int:
    attached = 0
    for draft in created:
        if sync_matched_program_attachment(db, draft, getattr(draft, "generation_meta_json", None)):
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
