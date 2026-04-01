from datetime import datetime

from pydantic import BaseModel


class EmailMessageRead(BaseModel):
    id: int
    thread_id: int
    run_id: int
    contact_id: int
    draft_id: int | None
    direction: str
    from_email: str | None
    to_email: str | None
    subject: str
    body: str
    provider_message_id: str | None
    rfc_message_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
