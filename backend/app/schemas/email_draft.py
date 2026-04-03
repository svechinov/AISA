from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.utils.attached_asset_ids import normalize_attached_asset_ids


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
