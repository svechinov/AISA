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


# Keys the dashboard needs from source_json for list views (avoid multi‑MB scraper blobs in GET /contacts/run).
_SOURCE_JSON_LIST_KEYS = frozenset(
    {
        "source",
        "replaces_contact_id",
        "role",
        "title",
        "job_title",
        "position",
        "linkedin",
    }
)

_PERSONALIZATION_LIST_KEYS = (
    "why_this_company",
    "offer_fit",
    "role_angle",
)


def slim_source_json_for_list(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in _SOURCE_JSON_LIST_KEYS:
        if k not in raw:
            continue
        v = raw[k]
        if v is None:
            continue
        if isinstance(v, str) and len(v) > 2000:
            v = v[:1999] + "…"
        out[k] = v
    return out


def slim_personalization_json_for_list(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in _PERSONALIZATION_LIST_KEYS:
        if k not in raw:
            continue
        v = raw[k]
        if v is None:
            continue
        if isinstance(v, str) and len(v) > 12000:
            v = v[:11999] + "…"
        out[k] = v
    return out


def contact_read_for_run_list(contact: Contact) -> ContactRead:
    """
    Same shape as ContactRead for PATCH responses, but GET /contacts/run trims JSON blobs
    so the UI list is not dominated by scraper / LLM payload size.
    """
    base = ContactRead.model_validate(contact)
    return base.model_copy(
        update={
            "source_json": slim_source_json_for_list(base.source_json),
            "personalization_json": slim_personalization_json_for_list(base.personalization_json),
        }
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
