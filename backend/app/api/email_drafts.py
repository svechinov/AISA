from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.db import get_db
from app.repositories.email_draft_repo import (
    delete_email_draft,
    get_email_draft,
    list_email_drafts_by_run,
    update_email_draft_fields,
    update_email_draft_review,
)
from app.schemas.email_draft import (
    EmailDraftEditUpdate,
    EmailDraftRead,
    EmailDraftReviewUpdate,
)
from app.workers.email_worker import regenerate_outbound_email_draft

router = APIRouter(prefix="/email-drafts", tags=["email-drafts"])


@router.get("/run/{run_id}", response_model=list[EmailDraftRead])
def list_email_drafts_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_email_drafts_by_run(db, run_id)


@router.get("/{draft_id}", response_model=EmailDraftRead)
def get_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return draft


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

    return update_email_draft_review(
        db=db,
        draft=draft,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )


@router.patch("/{draft_id}/edit", response_model=EmailDraftRead)
def edit_email_draft_route(
    draft_id: int,
    payload: EmailDraftEditUpdate,
    db: Session = Depends(get_db),
):
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    return update_email_draft_fields(
        db=db,
        draft=draft,
        subject=payload.subject,
        body=payload.body,
        review_notes=payload.review_notes,
        attached_asset_ids=payload.attached_asset_ids,
    )


@router.post("/{draft_id}/regenerate", response_model=EmailDraftRead)
def regenerate_email_draft_route(draft_id: int, db: Session = Depends(get_db)):
    try:
        return regenerate_outbound_email_draft(db, draft_id)
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
