from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.repositories.contact_repo import (
    get_contact,
    list_contacts_by_run,
    update_contact_fields,
    update_contact_review,
)
from app.schemas.contact import (
    ContactEditUpdate,
    ContactRead,
    ContactReviewCountsRead,
    ContactReviewUpdate,
    ContactRunBucketResponse,
    contact_read_for_run_list,
)
from app.services.contact_review_bucket import ALL_REVIEW_BUCKETS, filter_contacts_by_review_bucket, review_counts_from_contacts
from app.schemas.email_draft import EmailDraftRead
from app.workers.email_worker import (
    ensure_outreach_draft_for_contact,
    materialize_outreach_draft_for_sendable_contact,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _background_ensure_outreach_draft(contact_id: int) -> None:
    """Run after HTTP response — LLM draft generation must not block PATCH /review."""
    db = SessionLocal()
    try:
        contact = get_contact(db, contact_id)
        if contact and contact.review_status in {"approved", "edited"}:
            ensure_outreach_draft_for_contact(db, contact)
    finally:
        db.close()


@router.get("/run/{run_id}", response_model=list[ContactRead] | ContactRunBucketResponse)
def list_contacts_for_run(
    run_id: int,
    review_bucket: str | None = Query(
        None,
        description="If set (pending|approved|…|no_email), response is {review_counts, contacts} for that tab only; "
        "omit for full list (TrackingView, scripts). DB still loads the full run once for dedupe + counts.",
    ),
    db: Session = Depends(get_db),
):
    """
    List contacts for one run only (`run_id` filter — not all projects).

    Without `review_bucket`: JSON array of ContactRead (legacy).

    With `review_bucket`: JSON object with `review_counts` for all tabs and `contacts` only for the
    requested tab (smaller payload). Note: the repository still reads all contact rows for
    this run to apply dedupe and compute accurate counts.
    """
    rows = list_contacts_by_run(db, run_id)
    counts_dict = review_counts_from_contacts(rows)
    if review_bucket is None:
        return [contact_read_for_run_list(c) for c in rows]
    if review_bucket not in ALL_REVIEW_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_bucket. Use one of: {', '.join(ALL_REVIEW_BUCKETS)}",
        )
    filtered = filter_contacts_by_review_bucket(rows, review_bucket)
    return ContactRunBucketResponse(
        review_counts=ContactReviewCountsRead(**counts_dict),
        contacts=[contact_read_for_run_list(c) for c in filtered],
    )


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
    background_tasks: BackgroundTasks,
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
        background_tasks.add_task(_background_ensure_outreach_draft, updated.id)
    return updated


@router.patch("/{contact_id}/edit", response_model=ContactRead)
def edit_contact_route(
    contact_id: int,
    payload: ContactEditUpdate,
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(_background_ensure_outreach_draft, updated.id)
    return updated
