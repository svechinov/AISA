from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.db import get_db
from app.repositories.email_draft_repo import (
    bulk_set_attached_assets_for_approved_drafts,
    bulk_set_attached_assets_for_pending_drafts,
    delete_email_draft,
    get_email_draft,
    list_email_drafts_by_run,
    list_email_drafts_by_run_paginated,
    update_email_draft_fields,
    update_email_draft_review,
)
from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_email_draft
from app.schemas.email_draft import (
    EmailDraftEditUpdate,
    EmailDraftListRead,
    EmailDraftRead,
    EmailDraftReviewUpdate,
    PaginatedEmailDraftListResponse,
    email_draft_to_list_read,
    email_draft_to_read,
)
from app.workers.email_worker import regenerate_outbound_email_draft

router = APIRouter(prefix="/email-drafts", tags=["email-drafts"])


@router.get("/run/{run_id}", response_model=list[EmailDraftListRead] | PaginatedEmailDraftListResponse)
def list_email_drafts_for_run(
    run_id: int,
    limit: int | None = Query(
        None,
        ge=1,
        le=5000,
        description="If set, response is paginated {items,total,limit,offset}. If omitted, legacy array.",
    ),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Optional search on company, to, subject, body (ilike)."),
    include_body: bool = Query(
        False,
        description="If true, each item includes full `body` (Human UI review). Omit for compact list payloads.",
    ),
    db: Session = Depends(get_db),
):
    if limit is None:
        return [
            email_draft_to_list_read(db, d, include_body=include_body)
            for d in list_email_drafts_by_run(db, run_id)
        ]
    rows, total = list_email_drafts_by_run_paginated(db, run_id, limit=limit, offset=offset, q=q)
    off = max(0, offset)
    return PaginatedEmailDraftListResponse(
        items=[email_draft_to_list_read(db, d, include_body=include_body) for d in rows],
        total=total,
        limit=limit,
        offset=off,
    )


@router.get("/{draft_id}", response_model=EmailDraftRead)
def get_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return email_draft_to_read(db, draft)


@router.patch("/{draft_id}/review", response_model=EmailDraftRead)
def review_email_draft_route(
    draft_id: int,
    payload: EmailDraftReviewUpdate,
    db: Session = Depends(get_db),
):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    if payload.review_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="review_status must be approved or rejected")

    updated = update_email_draft_review(
        db=db,
        draft=draft,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )
    return email_draft_to_read(db, updated)


@router.patch("/{draft_id}/edit", response_model=EmailDraftRead)
def edit_email_draft_route(
    draft_id: int,
    payload: EmailDraftEditUpdate,
    db: Session = Depends(get_db),
):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    updated = update_email_draft_fields(
        db=db,
        draft=draft,
        subject=payload.subject,
        body=payload.body,
        review_notes=payload.review_notes,
        attached_asset_ids=payload.attached_asset_ids,
    )
    if payload.apply_assets_to_pending_drafts:
        asset_src = (
            payload.attached_asset_ids
            if payload.attached_asset_ids is not None
            else effective_attached_asset_ids_for_email_draft(db, updated)
        )
        bulk_set_attached_assets_for_pending_drafts(
            db,
            updated.run_id,
            normalize_attached_asset_ids(asset_src),
        )
        db.refresh(updated)
    if payload.apply_assets_to_approved_drafts:
        asset_src = (
            payload.attached_asset_ids
            if payload.attached_asset_ids is not None
            else effective_attached_asset_ids_for_email_draft(db, updated)
        )
        bulk_set_attached_assets_for_approved_drafts(
            db,
            updated.run_id,
            normalize_attached_asset_ids(asset_src),
        )
        db.refresh(updated)
    return email_draft_to_read(db, updated)


@router.post("/{draft_id}/regenerate", response_model=EmailDraftRead)
def regenerate_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    try:
        draft = regenerate_outbound_email_draft(db, draft_id)
        return email_draft_to_read(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{draft_id}", status_code=204, response_class=Response)
def delete_dead_mailbox_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    """Hard-delete a draft that was marked dead mailbox (Review workspace cleanup)."""
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    if draft.tracking_status != "dead_mailbox":
        raise HTTPException(
            status_code=400,
            detail="Only drafts with tracking dead mailbox can be deleted",
        )
    delete_email_draft(db, draft)
    return Response(status_code=204)
