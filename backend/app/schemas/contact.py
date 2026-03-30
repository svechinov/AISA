from datetime import datetime

from pydantic import BaseModel


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
    review_status: str
    review_notes: str | None
    reviewed_at: datetime | None
    email_health: str
    last_contact_event_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


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
