from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from sqlalchemy.orm import Session

from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_email_draft
from app.utils.email_draft_generation_meta import (
    effective_generation_meta_json,
    effective_generation_meta_json_for_list,
    effective_prompt_setup_text_used,
)
from app.utils.email_preview import email_body_preview_text


class EmailDraftRead(BaseModel):
    id: int
    run_id: int
    contact_id: int
    company: str | None
    to_email: str | None
    subject: str
    body: str
    status: str
    review_status: str
    review_notes: str | None
    tracking_status: str
    provider_message_id: str | None
    thread_id: str | None
    error_message: str | None
    last_event_at: datetime | None
    sent_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    attached_asset_ids: list[int] = Field(default_factory=list)
    generation_meta_json: dict | None = None

    @field_validator("attached_asset_ids", mode="before")
    @classmethod
    def _attached_asset_ids(cls, v):
        return normalize_attached_asset_ids(v)

    class Config:
        from_attributes = True


class EmailDraftListRead(BaseModel):
    """List rows: optional full body when include_body=1; else body_preview + GET /email-drafts/{id} for edit."""

    id: int
    run_id: int
    contact_id: int
    company: str | None
    to_email: str | None
    subject: str
    body_preview: str
    #: Present when GET /email-drafts/run/:id?include_body=1 (Human UI review — full draft text).
    body: str | None = None
    status: str
    review_status: str
    review_notes: str | None
    tracking_status: str
    error_message: str | None
    attached_asset_ids: list[int] = Field(default_factory=list)
    #: Snapshot of Prompt setup text used when this draft was generated (from generation_meta_json).
    prompt_setup_text_used: str | None = None
    #: Trimmed vs GET /email-drafts/:id — no duplicate ``prompt_setup_text_used`` (see top-level field).
    generation_meta_json: dict | None = None

    @field_validator("attached_asset_ids", mode="before")
    @classmethod
    def _attached_asset_ids(cls, v):
        return normalize_attached_asset_ids(v)

    class Config:
        from_attributes = True


class PaginatedEmailDraftListResponse(BaseModel):
    items: list[EmailDraftListRead]
    total: int
    limit: int
    offset: int


def _prompt_setup_used_from_draft_row(d) -> str | None:
    return effective_prompt_setup_text_used(d)


def _outbound_error_message_for_api(raw: str | None) -> str | None:
    """
    Hide known-fixed internal attachment errors (any wording / Gmail wrapper) — DB may still store the
    old string until the next successful send.
    """
    if not raw or not str(raw).strip():
        return None
    if "simplenamespace" in str(raw).lower():
        return None
    return raw


def email_draft_to_list_read(
    db: Session,
    d,
    *,
    include_body: bool = False,
) -> EmailDraftListRead:
    preview = email_body_preview_text(d.body)
    body_full: str | None = (d.body or "") if include_body else None
    return EmailDraftListRead(
        id=d.id,
        run_id=d.run_id,
        contact_id=d.contact_id,
        company=d.company,
        to_email=d.to_email,
        subject=d.subject,
        body_preview=preview,
        body=body_full,
        status=d.status,
        review_status=d.review_status,
        review_notes=d.review_notes,
        tracking_status=d.tracking_status,
        error_message=_outbound_error_message_for_api(d.error_message),
        attached_asset_ids=effective_attached_asset_ids_for_email_draft(db, d),
        prompt_setup_text_used=_prompt_setup_used_from_draft_row(d),
        generation_meta_json=effective_generation_meta_json_for_list(d),
    )


def email_draft_to_read(db: Session, d) -> EmailDraftRead:
    return EmailDraftRead(
        id=d.id,
        run_id=d.run_id,
        contact_id=d.contact_id,
        company=d.company,
        to_email=d.to_email,
        subject=d.subject,
        body=d.body,
        status=d.status,
        review_status=d.review_status,
        review_notes=d.review_notes,
        tracking_status=d.tracking_status,
        provider_message_id=d.provider_message_id,
        thread_id=d.thread_id,
        error_message=_outbound_error_message_for_api(d.error_message),
        last_event_at=d.last_event_at,
        sent_at=d.sent_at,
        reviewed_at=d.reviewed_at,
        created_at=d.created_at,
        attached_asset_ids=effective_attached_asset_ids_for_email_draft(db, d),
        generation_meta_json=effective_generation_meta_json(d),
    )


class EmailDraftReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class EmailDraftEditUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    review_notes: str | None = None
    attached_asset_ids: list[int] | None = None
    #: When true, set the same attached_asset_ids on every pending-review draft in the run (after this edit).
    apply_assets_to_pending_drafts: bool = False
    #: When true, set the same attached_asset_ids on every approved/edited draft in the run (Approved tab).
    apply_assets_to_approved_drafts: bool = False
