from datetime import datetime

from pydantic import BaseModel


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

    class Config:
        from_attributes = True


class ReplyDraftReviewUpdate(BaseModel):
    review_status: str
    review_notes: str | None = None


class ReplyDraftEditUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    review_notes: str | None = None
