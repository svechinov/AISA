from pydantic import BaseModel


class TrackingEventCreate(BaseModel):
    payload_json: dict | None = None
    error_message: str | None = None
