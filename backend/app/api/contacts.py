from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.repositories.contact_repo import (
    create_contact,
    dedupe_contact_minimals_for_run,
    get_contact,
    hydrate_contacts_for_list_read,
    list_contacts_by_run,
    update_contact_fields,
    update_contact_review,
)
from app.repositories.run_repo import get_run
from app.schemas.contact import (
    ContactEditUpdate,
    ContactRead,
    ContactReviewCountsRead,
    ContactReviewUpdate,
    ContactRunBucketResponse,
    PaginatedContactsRunResponse,
    contact_matches_list_search,
    contact_matches_minimal_search,
)
from pydantic import BaseModel

class GenerateCompanyLeadsRequest(BaseModel):
    company_name: str
    website: str | None = None
    target_roles: str | None = None

class ManualContactCreateRequest(BaseModel):
    company: str
    name: str | None = None
    role: str | None = None
    email: str | None = None
    linkedin: str | None = None

from app.services.contact_company_ai_fit import contact_read_with_ai_fit, contact_reads_for_run_with_ai_fit
from app.services.contact_review_bucket import (
    ALL_REVIEW_BUCKETS,
    review_bucket_for_contact_minimal,
    review_counts_from_minimals,
)
from app.schemas.email_draft import EmailDraftRead, email_draft_to_read
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


@router.get(
    "/run/{run_id}",
    response_model=list[ContactRead] | PaginatedContactsRunResponse | ContactRunBucketResponse,
)
def list_contacts_for_run(
    run_id: int,
    review_bucket: str | None = Query(
        None,
        description="If set (pending|approved|…|no_email), response is {review_counts, contacts} for that tab only. "
        "Scalar columns only for dedupe + counts; full ORM rows are loaded for the returned page only.",
    ),
    limit: int | None = Query(
        None,
        ge=1,
        le=5000,
        description="If set, response is PaginatedContactsRunResponse (or paginated ContactRunBucketResponse). "
        "If omitted, legacy JSON array (no review_bucket) or full tab list (with review_bucket).",
    ),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Case-insensitive substring filter on company, name, role, email, linkedin."),
    db: Session = Depends(get_db),
):
    """
    List contacts for one run only (`run_id` filter — not all projects).

    Without `review_bucket`: JSON array of ContactRead when `limit` is omitted (legacy).
    With `limit`: PaginatedContactsRunResponse with `items`, `total`, `limit`, `offset`.

    With `review_bucket`: JSON object with `review_counts` for all tabs and `contacts` for the
    requested tab. When `limit` is set, `contacts` is a page and `total` is the filtered count.

    When `limit` or `review_bucket` is set: dedupe uses scalar columns only; ``Contact`` rows (JSON
    deferred) are hydrated only for the returned slice — not for every contact in the run.
    """
    # Legacy: raw JSON array, no query params — same behavior as before (full deduped list).
    if limit is None and review_bucket is None:
        rows = list_contacts_by_run(db, run_id, load_json=False)
        filtered = [c for c in rows if contact_matches_list_search(c, q)]
        return contact_reads_for_run_with_ai_fit(db, run_id, filtered)

    minimals = dedupe_contact_minimals_for_run(db, run_id)

    if review_bucket is not None:
        if review_bucket not in ALL_REVIEW_BUCKETS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid review_bucket. Use one of: {', '.join(ALL_REVIEW_BUCKETS)}",
            )
        counts_dict = review_counts_from_minimals(minimals)
        filtered_m = [
            m
            for m in minimals
            if review_bucket_for_contact_minimal(m) == review_bucket and contact_matches_minimal_search(m, q)
        ]
        total_f = len(filtered_m)
        off = max(0, offset)
        if limit is None:
            page_m = filtered_m
            lim = total_f
            off_out = 0
        else:
            lim = limit
            page_m = filtered_m[off : off + limit]
            off_out = off
        hydrated = hydrate_contacts_for_list_read(db, [m.id for m in page_m])
        return ContactRunBucketResponse(
            review_counts=ContactReviewCountsRead(**counts_dict),
            contacts=contact_reads_for_run_with_ai_fit(db, run_id, hydrated),
            total=total_f,
            limit=lim,
            offset=off_out,
        )

    assert limit is not None
    filtered_m = [m for m in minimals if contact_matches_minimal_search(m, q)]
    total_f = len(filtered_m)
    off = max(0, offset)
    page_m = filtered_m[off : off + limit]
    hydrated = hydrate_contacts_for_list_read(db, [m.id for m in page_m])
    return PaginatedContactsRunResponse(
        items=contact_reads_for_run_with_ai_fit(db, run_id, hydrated),
        total=total_f,
        limit=limit,
        offset=off,
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
    return email_draft_to_read(db, draft)


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
    return contact_read_with_ai_fit(db, updated)


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
    return contact_read_with_ai_fit(db, updated)


@router.post("/{contact_id}/deep_osint")
def deep_osint_contact_route(
    contact_id: int,
    force: bool = Query(False, description="Bypass the verification gate and run Agent B anyway."),
    db: Session = Depends(get_db),
):
    """Run deep person-level OSINT (Agent B) for this contact and store the personal dossier.

    Manual trigger (UI "Deep OSINT" button). Synchronous: gathers public info on the person via
    Tavily, extracts a structured dossier via the LLM gateway (OpenAI), and saves it to
    contact.personalization_json["person_osint"] — which the UI surfaces as "View Deep OSINT" and
    the email generator uses as the personal hook. Uses the editable run_setup.deep_osint_prompt.

    Gate (token economy): Agent B runs only on verified/target contacts — a usable email and
    status "valid" (verified by discovery or validation). Unverified/invalid contacts are rejected
    with 422 so we don't spend Deep Research tokens on dead leads. Pass force=true to override.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from app.services.deep_lpr_osint import perform_deep_lpr_osint

    contact = get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    if not force:
        email = (contact.email or "").strip()
        has_email = bool(email) and "@" in email
        sj = contact.source_json if isinstance(contact.source_json, dict) else {}
        smtp_rejected = sj.get("email_verification") == "rejected"
        if not has_email or contact.status != "valid" or smtp_rejected:
            reason = (
                "the SMTP probe rejected this mailbox"
                if smtp_rejected
                else "contact needs a verified email (status='valid')"
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Agent B gate: {reason}. "
                    "Run validation/enrichment first, or retry with force=true."
                ),
            )

    contact.ai_pipeline_status = "osint_running"
    db.commit()

    result = perform_deep_lpr_osint(db, contact)
    if not isinstance(result, dict) or result.get("error"):
        contact.ai_pipeline_status = "needs_osint"  # revert so it can be retried
        db.commit()
        db.refresh(contact)
        detail = result.get("error") if isinstance(result, dict) else "unknown error"
        raise HTTPException(status_code=502, detail=f"Deep OSINT failed: {detail}")

    pj = dict(contact.personalization_json or {})
    pj["person_osint"] = result
    contact.personalization_json = pj
    flag_modified(contact, "personalization_json")
    contact.ai_pipeline_status = "profiled"
    db.commit()
    db.refresh(contact)

    return contact_read_with_ai_fit(db, contact)


@router.post("/run/{run_id}/manual", response_model=ContactRead)
def add_manual_contact_route(
    run_id: int,
    payload: ManualContactCreateRequest,
    db: Session = Depends(get_db),
):
    """Manually add a single contact to a run."""
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
        
    c = create_contact(
        db=db,
        run_id=run_id,
        company=payload.company.strip() if payload.company else None,
        website=None,
        name=payload.name.strip() if payload.name else None,
        role=payload.role.strip() if payload.role else None,
        email=payload.email.strip() if payload.email else None,
        linkedin=payload.linkedin.strip() if payload.linkedin else None,
        status="valid",
        review_status="pending"
    )
    
    return contact_read_with_ai_fit(db, c)
