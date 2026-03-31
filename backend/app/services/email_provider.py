from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from app.config import settings
from app.services.gmail_oauth import (
    GmailOAuthError,
    clear_google_refresh_token_if_allowed,
    google_client_configured,
    google_refresh_token_value,
    send_html_via_gmail,
    send_mime_gmail,
)

logger = logging.getLogger(__name__)


def send_email_via_provider(
    to_email: str,
    subject: str,
    body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Send outbound email. attachments: optional list of
    {"filename": str, "content": bytes, "mime_type": str}.
    Uses Gmail API when GOOGLE_REFRESH_TOKEN + client credentials are set.
    If not, raises unless EMAIL_ALLOW_MOCK=true (legacy mock for offline dev only).
    """
    if not to_email or "@" not in to_email:
        raise ValueError("Invalid recipient email")

    att_list = attachments or []

    if google_client_configured() and google_refresh_token_value():
        try:
            if att_list:
                return send_mime_gmail(
                    to_email=to_email.strip(),
                    subject=subject,
                    body_html=body,
                    attachments=att_list,
                )
            return send_html_via_gmail(to_email=to_email.strip(), subject=subject, body_html=body)
        except GmailOAuthError as e:
            clear_google_refresh_token_if_allowed()
            raise ValueError(
                "Gmail authorization failed or expired. Open Drafts → connect Gmail again. "
                f"Details: {e}",
            ) from e
        except httpx.HTTPError as e:
            logger.exception("Gmail HTTP transport error")
            raise ValueError(
                "Could not reach Gmail/Google over the network (timeout or connection error). "
                f"Details: {e}",
            ) from e
        except (UnicodeEncodeError, UnicodeError) as e:
            logger.exception("Gmail MIME encoding error")
            raise ValueError(
                f"Email body or headers contain characters that could not be encoded for sending: {e}",
            ) from e
        except Exception as e:
            logger.exception("Unexpected Gmail send error")
            raise ValueError(
                f"Gmail send failed ({type(e).__name__}): {e}",
            ) from e

    if not settings.EMAIL_ALLOW_MOCK:
        raise ValueError(
            "Gmail is not configured in this API process (missing client id/secret or GOOGLE_REFRESH_TOKEN), "
            "and EMAIL_ALLOW_MOCK is false — no email was sent. Check GET /setup/status (gmail_send_ready), "
            "fix backend/.env, recreate the backend container if you use Docker, or set EMAIL_ALLOW_MOCK=true "
            "only for offline development without Gmail.",
        )

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
