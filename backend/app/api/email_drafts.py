from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_draft_repo import (
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
    )
