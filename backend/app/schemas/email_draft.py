from datetime import datetime

from pydantic import BaseModel


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

    class Config:
        from_attributes = True


class EmailDraftReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class EmailDraftEditUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    review_notes: str | None = None
