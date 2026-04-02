from datetime import datetime

from pydantic import BaseModel


class ThreadDeliveryLlmAnalyzeResponse(BaseModel):
    delivery_issue: str
    confidence: str
    reason: str
    error: str | None = None


class EmailThreadRead(BaseModel):
    id: int
    run_id: int
    contact_id: int
    draft_id: int | None
    # When draft_id is null, backend fills this from Gmail thread / message correlation (import-first rows).
    effective_draft_id: int | None = None
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
