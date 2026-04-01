from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.contact_repo import (
    get_contact,
    list_contacts_by_run,
    update_contact_fields,
    update_contact_review,
)
from app.schemas.contact import ContactEditUpdate, ContactRead, ContactReviewUpdate
from app.schemas.email_draft import EmailDraftRead
from app.workers.email_worker import (
    ensure_outreach_draft_for_contact,
    materialize_outreach_draft_for_sendable_contact,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("/run/{run_id}", response_model=list[ContactRead])
def list_contacts_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_contacts_by_run(db, run_id)


@router.post("/{contact_id}/create-draft", response_model=EmailDraftRead)
def create_draft_for_contact_route(contact_id: int, db: Session = Depends(get_db)):
    """Manual recovery when an approved contact has no email draft yet."""
    contact = get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.review_status not in {"approved", "edited"}:
        raise HTTPException(
            status_code=400,
            detail="Contact must be approved or edited before creating a draft",
        )
    if contact.status != "valid":
        raise HTTPException(status_code=400, detail="Contact must be validated (valid)")
    if not (contact.email or "").strip():
        raise HTTPException(status_code=400, detail="Contact has no email address")
    try:
        draft = materialize_outreach_draft_for_sendable_contact(db, contact)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not draft:
        raise HTTPException(
            status_code=400,
            detail="Could not create draft — workflow may not support outreach, or contact is not eligible.",
        )
    return draft


@router.patch("/{contact_id}/review", response_model=ContactRead)
def review_contact_route(
    contact_id: int,
    payload: ContactReviewUpdate,
    db: Session = Depends(get_db),
):
    contact = get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    if payload.review_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="review_status must be approved or rejected")

    if payload.review_status == "approved" and not (contact.email or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Cannot approve a contact with no email — add an address via Edit first.",
        )

    updated = update_contact_review(
        db=db,
        contact=contact,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )
    if updated.review_status in {"approved", "edited"}:
        ensure_outreach_draft_for_contact(db, updated)
    return updated


@router.patch("/{contact_id}/edit", response_model=ContactRead)
def edit_contact_route(
    contact_id: int,
    payload: ContactEditUpdate,
    db: Session = Depends(get_db),
):
    contact = get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    updated = update_contact_fields(
        db=db,
        contact=contact,
        company=payload.company,
        website=payload.website,
        name=payload.name,
        role=payload.role,
        email=payload.email,
        linkedin=payload.linkedin,
        confidence=payload.confidence,
        review_notes=payload.review_notes,
    )
    ensure_outreach_draft_for_contact(db, updated)
    return updated
