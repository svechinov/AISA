from __future__ import annotations

import uuid
from typing import Any


def send_email_via_provider(
    to_email: str,
    subject: str,
    body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Send outbound email. attachments: optional list of
    {"filename": str, "content": bytes, "mime_type": str}.
    """
    if not to_email or "@" not in to_email:
        raise ValueError("Invalid recipient email")

    att_list = attachments or []
    attachment_ids = [f"mock-att-{uuid.uuid4()}" for _ in att_list]

    return {
        "provider_message_id": f"mock-msg-{uuid.uuid4()}",
        "thread_id": f"mock-thread-{uuid.uuid4()}",
        "provider": "mock",
        "accepted": True,
        "to_email": to_email,
        "subject": subject,
        "attachment_count": len(att_list),
        "attachment_ids": attachment_ids,
    }
