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

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("/run/{run_id}", response_model=list[ContactRead])
def list_contacts_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_contacts_by_run(db, run_id)


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

    return update_contact_review(
        db=db,
        contact=contact,
        review_status=payload.review_status,
        review_notes=payload.review_notes,
    )


@router.patch("/{contact_id}/edit", response_model=ContactRead)
def edit_contact_route(
    contact_id: int,
    payload: ContactEditUpdate,
    db: Session = Depends(get_db),
):
    contact = get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    return update_contact_fields(
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
