from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.asset_packet_repo import get_packet_by_reply_draft_id
from app.repositories.reply_draft_repo import (
    get_reply_draft,
    list_reply_drafts_by_run,
    list_reply_drafts_by_thread,
    update_reply_draft_fields,
    update_reply_draft_review,
)
from app.schemas.reply_draft import (
    ReplyDraftEditUpdate,
    ReplyDraftRead,
    ReplyDraftReviewUpdate,
)
from app.services.reply_draft_service import generate_reply_draft_for_thread
from app.services.reply_sender import build_reply_send_payload, send_one_reply_draft

router = APIRouter(prefix="/reply-drafts", tags=["reply-drafts"])


@router.get("/run/{run_id}", response_model=list[ReplyDraftRead])
def list_reply_drafts_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_reply_drafts_by_run(db, run_id)


@router.get("/thread/{thread_id}", response_model=list[ReplyDraftRead])
def list_reply_drafts_for_thread(thread_id: int, db: Session = Depends(get_db)):
    return list_reply_drafts_by_thread(db, thread_id)


@router.post("/thread/{thread_id}/generate")
def generate_reply_draft_route(thread_id: int, db: Session = Depends(get_db)):
    try:
        return generate_reply_draft_for_thread(db, thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/{draft_id}/review", response_model=ReplyDraftRead)
def review_reply_draft_route(
    draft_id: int,
    payload: ReplyDraftReviewUpdate,
    db: Session = Depends(get_db),
):
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Reply draft not found")

    if payload.review_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="review_status must be approved or rejected")

    return update_reply_draft_review(
        db=db,
        draft=draft,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )


@router.patch("/{draft_id}/edit", response_model=ReplyDraftRead)
def edit_reply_draft_route(
    draft_id: int,
    payload: ReplyDraftEditUpdate,
    db: Session = Depends(get_db),
):
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Reply draft not found")

    return update_reply_draft_fields(
        db=db,
        draft=draft,
        subject=payload.subject,
        body=payload.body,
        review_notes=payload.review_notes,
    )


@router.post("/{draft_id}/send")
def send_reply_draft_route(draft_id: int, db: Session = Depends(get_db)):
    try:
        return send_one_reply_draft(db, draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{draft_id}/send-preview")
def reply_draft_send_preview(draft_id: int, db: Session = Depends(get_db)):
    """Read-only: same body/attachment split as send (link-only Materials + MIME attachments)."""
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Reply draft not found")
    try:
        payload = build_reply_send_payload(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        attached = get_packet_by_reply_draft_id(db, draft.id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    will_lock = bool(attached and attached.status in ("draft", "approved"))
    return {
        "base_body": payload["base_body"],
        "packet_block": payload["packet_block"],
        "final_body": payload["final_body"],
        "attached_packet_id": payload["attached_packet_id"],
        "attachment_candidates": payload["attachment_candidates"],
        "real_attachments": payload["real_attachments"],
        "link_only_assets": payload["link_only_assets"],
        "skipped_attachments": payload["skipped_attachments"],
        "attached_asset_ids": payload["attached_asset_ids"],
        "linked_asset_ids": payload["linked_asset_ids"],
        "will_lock_packet": will_lock,
        "attached_packet_status": attached.status if attached else None,
    }


@router.get("/{draft_id}", response_model=ReplyDraftRead)
def get_reply_draft_route(draft_id: int, db: Session = Depends(get_db)):
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Reply draft not found")
    return draft
