from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.utils.attached_asset_ids import normalize_attached_asset_ids


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


class ReplyDraftReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class ReplyDraftEditUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    review_notes: str | None = None
    attached_asset_ids: list[int] | None = None
