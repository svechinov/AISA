from datetime import datetime

from pydantic import BaseModel, Field

from app.models.contact import Contact


class ContactRead(BaseModel):
    id: int
    run_id: int
    company: str | None
    website: str | None
    name: str | None
    role: str | None
    email: str | None
    linkedin: str | None
    status: str
    confidence: str | None
    source_json: dict
    personalization_json: dict = Field(default_factory=dict)
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    email_health: str
    last_contact_event_at: datetime | None
    gmail_history_status: str | None = None
    gmail_history_checked_at: datetime | None = None
    gmail_inbox_imported_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ContactReviewCountsRead(BaseModel):
    """Per-tab counts for Review contacts (same buckets as contact_review_bucket service)."""

    pending: int = 0
    approved: int = 0
    rejected: int = 0
    bounced: int = 0
    dead_mailbox: int = 0
    no_email: int = 0


class ContactRunBucketResponse(BaseModel):
    """When GET /contacts/run/{id}?review_bucket=… — full tab counts + only that tab’s rows."""

    review_counts: ContactReviewCountsRead
    contacts: list[ContactRead]
    total: int
    limit: int
    offset: int


class PaginatedContactsRunResponse(BaseModel):
    """Deduped contacts for a run (same order as list_contacts_by_run), paginated slice."""

    items: list[ContactRead]
    total: int
    limit: int
    offset: int


def contact_matches_list_search(contact: Contact, q: str | None) -> bool:
    """Case-insensitive substring match on company, name, role, email, linkedin."""
    if not q or not str(q).strip():
        return True
    needle = str(q).strip().lower()
    for attr in ("company", "name", "role", "email", "linkedin"):
        v = getattr(contact, attr, None) or ""
        if needle in str(v).lower():
            return True
    return False


def contact_read_for_run_list(contact: Contact) -> ContactRead:
    """
    GET /contacts/run list rows: same shape as ContactRead but **does not** read ``source_json`` /
    ``personalization_json`` from the ORM (those columns stay deferred). Empty dicts keep payloads small
    and avoid JSON parse + transfer; full blobs come from GET/PATCH /contacts/:id when needed.
    """
    return ContactRead(
        id=contact.id,
        run_id=contact.run_id,
        company=contact.company,
        website=contact.website,
        name=contact.name,
        role=contact.role,
        email=contact.email,
        linkedin=contact.linkedin,
        status=contact.status,
        confidence=contact.confidence,
        source_json={},
        personalization_json={},
        review_status=contact.review_status,
        review_notes=contact.review_notes,
        reviewed_at=contact.reviewed_at,
        email_health=contact.email_health,
        last_contact_event_at=contact.last_contact_event_at,
        gmail_history_status=contact.gmail_history_status,
        gmail_history_checked_at=contact.gmail_history_checked_at,
        gmail_inbox_imported_at=contact.gmail_inbox_imported_at,
        created_at=contact.created_at,
    )


class ContactReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class ContactEditUpdate(BaseModel):
    company: str | None = None
    website: str | None = None
    name: str | None = None
    role: str | None = None
    email: str | None = None
    linkedin: str | None = None
    confidence: str | None = None
    review_notes: str | None = None
