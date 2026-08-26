from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.services.gmail_oauth import (
    GmailOAuthError,
    clear_google_refresh_token_if_allowed,
    google_client_configured,
    google_refresh_token_value,
    send_html_via_gmail,
    send_mime_gmail,
)
from app.services.generic_smtp_service import send_email_via_smtp_account
from app.services.smtp_rotator_service import get_next_available_smtp_account, increment_account_usage
from app.services.yandex_mail_service import send_email_yandex

logger = logging.getLogger(__name__)


def _provider_order() -> list[str]:
    """EMAIL_PROVIDER selects the transport: 'gmail' (Gmail API via OAuth) or 'smtp'
    (rotator over smtp_accounts with the SystemSetting Yandex fallback). The other
    transport stays available as fallback so a misconfigured primary degrades loudly
    in logs instead of silently dropping sends."""
    primary = (getattr(settings, "EMAIL_PROVIDER", None) or "gmail").strip().lower()
    return ["gmail", "smtp"] if primary != "smtp" else ["smtp", "gmail"]


def _send_via_gmail(
    to_email: str,
    subject: str,
    body: str,
    att_list: list[dict[str, Any]],
    mailbox_email: str | None = None,
    inline_images: list[dict[str, Any]] | None = None,
) -> dict:
    try:
        if att_list or inline_images:
            return send_mime_gmail(
                to_email=to_email.strip(),
                subject=subject,
                body_html=body,
                attachments=att_list,
                mailbox_email=mailbox_email,
                inline_images=inline_images,
            )
        return send_html_via_gmail(
            to_email=to_email.strip(),
            subject=subject,
            body_html=body,
            mailbox_email=mailbox_email,
        )
    except GmailOAuthError as e:
        clear_google_refresh_token_if_allowed(mailbox_email)
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


def _send_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    att_list: list[dict[str, Any]],
    db: Session | None,
) -> dict | None:
    """SMTP rotator over smtp_accounts, then the SystemSetting Yandex account.
    Returns None when no SMTP transport is configured/available (caller falls through).
    B-533: this fallback has no multipart/related support — it sends without the inline signature
    logo (the <img cid:...> tag falls back to its alt text). Gmail is the primary transport."""
    if db:
        account = get_next_available_smtp_account(db)
        if account:
            ok = send_email_via_smtp_account(
                account=account,
                to_address=to_email,
                subject=subject,
                body_html=body,
                attachments=att_list or None,
            )
            if ok:
                increment_account_usage(db, account.id)
                return {
                    "provider_message_id": f"{account.smtp_server}-msg-{uuid.uuid4()}",
                    "thread_id": f"{account.smtp_server}-thread-{uuid.uuid4()}",
                    "provider": account.smtp_server,
                    "from_email": account.email,
                    "accepted": True,
                    "to_email": to_email,
                    "subject": subject,
                    "attachment_count": len(att_list),
                    "attachment_ids": [],
                }
            logger.warning("SMTP account %s failed to send, trying Yandex fallback", account.email)
    if send_email_yandex(to_email, subject, body):
        return {
            "provider_message_id": f"yandex-system-msg-{uuid.uuid4()}",
            "thread_id": f"yandex-system-thread-{uuid.uuid4()}",
            "provider": "yandex-system",
            "from_email": None,
            "accepted": True,
            "to_email": to_email,
            "subject": subject,
            "attachment_count": len(att_list),
            "attachment_ids": [],
        }
    return None


def send_email_via_provider(
    to_email: str,
    subject: str,
    body: str,
    attachments: list[dict[str, Any]] | None = None,
    db: Session | None = None,
    mailbox_email: str | None = None,
    inline_images: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Send outbound email. attachments: optional list of
    {"filename": str, "content": bytes, "mime_type": str}.

    Transport order comes from EMAIL_PROVIDER (default gmail-first). Gmail requires
    GOOGLE_* client credentials + GOOGLE_REFRESH_TOKEN; SMTP requires a db session and
    rows in smtp_accounts (or the SystemSetting Yandex creds). If nothing is configured,
    raises unless EMAIL_ALLOW_MOCK=true (offline dev only).

    ``mailbox_email`` (B-071 stage B): which mailbox to send Gmail from — resolves per-mailbox
    creds via gmail_oauth._mailbox_creds; None (default) keeps today's single global mailbox.

    ``inline_images`` (B-533): cid: images referenced by body's <img src="cid:...">, e.g. from
    outbound_email_body.inline_images_for_email_html. When non-empty, the Gmail path always goes
    through send_mime_gmail (multipart/related), even with no regular attachments.
    """
    if not to_email or "@" not in to_email:
        raise ValueError("Invalid recipient email")

    att_list = attachments or []

    for provider in _provider_order():
        if provider == "gmail":
            if google_client_configured() and google_refresh_token_value(mailbox_email):
                return _send_via_gmail(to_email, subject, body, att_list, mailbox_email, inline_images)
        else:
            result = _send_via_smtp(to_email, subject, body, att_list, db)
            if result:
                return result

    if not settings.EMAIL_ALLOW_MOCK:
        raise ValueError(
            "No email transport is configured: Gmail is missing client id/secret or "
            "GOOGLE_REFRESH_TOKEN, and no active SMTP account / Yandex creds are set. "
            "Check GET /setup/status (gmail_send_ready), fix backend/.env, or set "
            "EMAIL_ALLOW_MOCK=true only for offline development.",
        )

    attachment_ids = [f"mock-att-{uuid.uuid4()}" for _ in att_list]

    return {
        "provider_message_id": f"mock-msg-{uuid.uuid4()}",
        "thread_id": f"mock-thread-{uuid.uuid4()}",
        "provider": "mock",
        "from_email": None,
        "accepted": True,
        "to_email": to_email,
        "subject": subject,
        "attachment_count": len(att_list),
        "attachment_ids": attachment_ids,
    }
