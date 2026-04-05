from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from sqlalchemy.orm import Session

from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_reply_draft
from app.utils.email_preview import email_body_preview_text


class ReplyDraftRead(BaseModel):
    id: int
    run_id: int
    thread_id: int
    contact_id: int
    reply_type: str
    to_email: str | None
    subject: str
    body: str
    status: str
    review_status: str
    review_notes: str | None
    provider_message_id: str | None
    error_message: str | None
    sent_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    attached_asset_ids: list[int] = Field(default_factory=list)

    @field_validator("attached_asset_ids", mode="before")
    @classmethod
    def _attached_asset_ids(cls, v):
        return normalize_attached_asset_ids(v)

    class Config:
        from_attributes = True


class ReplyDraftListRead(BaseModel):
    """List rows: no full body — use GET /reply-drafts/{id} for edit."""

    id: int
    run_id: int
    thread_id: int
    contact_id: int
    reply_type: str
    to_email: str | None
    subject: str
    body_preview: str
    status: str
    review_status: str
    review_notes: str | None
    provider_message_id: str | None
    error_message: str | None
    sent_at: datetime | None
    reviewed_at: datetime | None
    created_at: datetime
    attached_asset_ids: list[int] = Field(default_factory=list)

    @field_validator("attached_asset_ids", mode="before")
    @classmethod
    def _attached_asset_ids(cls, v):
        return normalize_attached_asset_ids(v)

    class Config:
        from_attributes = True


def reply_draft_to_list_read(db: Session, d) -> ReplyDraftListRead:
    return ReplyDraftListRead(
        id=d.id,
        run_id=d.run_id,
        thread_id=d.thread_id,
        contact_id=d.contact_id,
        reply_type=d.reply_type,
        to_email=d.to_email,
        subject=d.subject,
        body_preview=email_body_preview_text(d.body),
        status=d.status,
        review_status=d.review_status,
        review_notes=d.review_notes,
        provider_message_id=d.provider_message_id,
        error_message=d.error_message,
        sent_at=d.sent_at,
        reviewed_at=d.reviewed_at,
        created_at=d.created_at,
        attached_asset_ids=effective_attached_asset_ids_for_reply_draft(db, d),
    )


def reply_draft_to_read(db: Session, d) -> ReplyDraftRead:
    return ReplyDraftRead(
        id=d.id,
        run_id=d.run_id,
        thread_id=d.thread_id,
        contact_id=d.contact_id,
        reply_type=d.reply_type,
        to_email=d.to_email,
        subject=d.subject,
        body=d.body,
        status=d.status,
        review_status=d.review_status,
        review_notes=d.review_notes,
        provider_message_id=d.provider_message_id,
        error_message=d.error_message,
        sent_at=d.sent_at,
        reviewed_at=d.reviewed_at,
        created_at=d.created_at,
        attached_asset_ids=effective_attached_asset_ids_for_reply_draft(db, d),
    )


class ReplyDraftReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class ReplyDraftEditUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    review_notes: str | None = None
    attached_asset_ids: list[int] | None = None
