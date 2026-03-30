from datetime import datetime

from pydantic import BaseModel


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
