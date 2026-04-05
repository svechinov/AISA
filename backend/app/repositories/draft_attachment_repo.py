"""Ordered asset ids for email_drafts / reply_drafts — canonical store; legacy JSON column is cleared after backfill."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.email_draft_asset import EmailDraftAsset
from app.models.reply_draft_asset import ReplyDraftAsset


def list_asset_ids_for_email_draft(db: Session, email_draft_id: int) -> list[int]:
    rows = (
        db.query(EmailDraftAsset)
        .filter(EmailDraftAsset.email_draft_id == email_draft_id)
        .order_by(EmailDraftAsset.position.asc(), EmailDraftAsset.id.asc())
        .all()
    )
    return [r.asset_id for r in rows]


def list_asset_ids_for_reply_draft(db: Session, reply_draft_id: int) -> list[int]:
    rows = (
        db.query(ReplyDraftAsset)
        .filter(ReplyDraftAsset.reply_draft_id == reply_draft_id)
        .order_by(ReplyDraftAsset.position.asc(), ReplyDraftAsset.id.asc())
        .all()
    )
    return [r.asset_id for r in rows]


def replace_email_draft_assets(db: Session, email_draft_id: int, asset_ids: list[int]) -> None:
    db.query(EmailDraftAsset).filter(EmailDraftAsset.email_draft_id == email_draft_id).delete(
        synchronize_session=False,
    )
    for i, aid in enumerate(asset_ids):
        db.add(EmailDraftAsset(email_draft_id=email_draft_id, asset_id=int(aid), position=i))


def replace_reply_draft_assets(db: Session, reply_draft_id: int, asset_ids: list[int]) -> None:
    db.query(ReplyDraftAsset).filter(ReplyDraftAsset.reply_draft_id == reply_draft_id).delete(
        synchronize_session=False,
    )
    for i, aid in enumerate(asset_ids):
        db.add(ReplyDraftAsset(reply_draft_id=reply_draft_id, asset_id=int(aid), position=i))


def count_email_draft_assets(db: Session, email_draft_id: int) -> int:
    return db.query(EmailDraftAsset).filter(EmailDraftAsset.email_draft_id == email_draft_id).count()


def count_reply_draft_assets(db: Session, reply_draft_id: int) -> int:
    return db.query(ReplyDraftAsset).filter(ReplyDraftAsset.reply_draft_id == reply_draft_id).count()
