from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.utils.email_event_payload import effective_payload_json


class EmailEventRead(BaseModel):
    id: int
    run_id: int
    draft_id: int
    contact_id: int
    event_type: str
    provider_message_id: str | None
    payload_json: dict
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True


def email_event_to_read(e: Any) -> EmailEventRead:
    return EmailEventRead(
        id=e.id,
        run_id=e.run_id,
        draft_id=e.draft_id,
        contact_id=e.contact_id,
        event_type=e.event_type,
        provider_message_id=e.provider_message_id,
        payload_json=effective_payload_json(e),
        error_message=e.error_message,
        created_at=e.created_at,
    )
