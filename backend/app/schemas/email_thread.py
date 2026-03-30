from datetime import datetime

from pydantic import BaseModel


class EmailThreadRead(BaseModel):
    id: int
    run_id: int
    contact_id: int
    draft_id: int | None
    subject: str
    provider_thread_id: str | None
    status: str
    last_message_at: datetime | None
    created_at: datetime
    classification: str | None = None
    classification_confidence: str | None = None
    classification_reason: str | None = None

    class Config:
        from_attributes = True
