from pydantic import BaseModel


class MockReplyCreate(BaseModel):
    draft_id: int
    from_email: str
    to_email: str
    subject: str
    body: str
    provider_message_id: str | None = None
