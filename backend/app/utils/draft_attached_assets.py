"""Resolve library asset ids for drafts: canonical rows in email_draft_assets / reply_draft_assets."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.repositories.draft_attachment_repo import (
    count_email_draft_assets,
    count_reply_draft_assets,
    list_asset_ids_for_email_draft,
    list_asset_ids_for_reply_draft,
)
from app.utils.attached_asset_ids import normalize_attached_asset_ids


def effective_attached_asset_ids_for_email_draft(db: Session, draft) -> list[int]:
    if count_email_draft_assets(db, draft.id) > 0:
        return list_asset_ids_for_email_draft(db, draft.id)
    return normalize_attached_asset_ids(draft.attached_asset_ids)


def effective_attached_asset_ids_for_reply_draft(db: Session, draft) -> list[int]:
    """Prefer reply_draft_assets; fall back to JSON only if junction is empty (pre-migration rows)."""
    if count_reply_draft_assets(db, draft.id) > 0:
        return list_asset_ids_for_reply_draft(db, draft.id)
    return normalize_attached_asset_ids(draft.attached_asset_ids)
