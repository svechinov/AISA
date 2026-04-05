from datetime import datetime

from pydantic import BaseModel

from app.utils.email_preview import email_body_preview_text


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


class EmailMessageListRead(BaseModel):
    """Run-wide message list: no full body — use GET /email-threads/{thread_id}/messages for a thread."""

    id: int
    thread_id: int
    run_id: int
    contact_id: int
    draft_id: int | None
    direction: str
    from_email: str | None
    to_email: str | None
    subject: str
    body_preview: str
    provider_message_id: str | None
    rfc_message_id: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


def email_message_to_list_read(m) -> EmailMessageListRead:
    return EmailMessageListRead(
        id=m.id,
        thread_id=m.thread_id,
        run_id=m.run_id,
        contact_id=m.contact_id,
        draft_id=m.draft_id,
        direction=m.direction,
        from_email=m.from_email,
        to_email=m.to_email,
        subject=m.subject,
        body_preview=email_body_preview_text(m.body),
        provider_message_id=m.provider_message_id,
        rfc_message_id=m.rfc_message_id,
        created_at=m.created_at,
    )
