from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.yandex_mail_service import send_email_yandex
from app.services.generic_smtp_service import send_email_via_smtp_account
from app.services.smtp_rotator_service import get_next_available_smtp_account, increment_account_usage
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

def send_email_via_provider(
    to_email: str,
    subject: str,
    body: str,
    attachments: list[dict[str, Any]] | None = None,
    db: Session | None = None,
) -> dict:
    """
    Send outbound email using SMTP Load Balancer.
    """
    if not to_email or "@" not in to_email:
        raise ValueError("Invalid recipient email")

    success = False
    provider_name = "unknown"
    account_email = None

    if db:
        account = get_next_available_smtp_account(db)
        if account:
            success = send_email_via_smtp_account(
                account=account,
                to_address=to_email,
                subject=subject,
                body_html=body,
                attachments=attachments
            )
            if success:
                increment_account_usage(db, account.id)
                provider_name = account.smtp_server
                account_email = account.email
        else:
            logger.warning("No active SMTP accounts available, falling back to SystemSetting Yandex.")

    # Fallback if no account in DB or if it failed
    if not success:
        success = send_email_yandex(to_email, subject, body)
        if not success:
            raise ValueError("Failed to send email via any SMTP provider")
        provider_name = "yandex-system"

    return {
        "provider_message_id": f"{provider_name}-msg-{uuid.uuid4()}",
        "thread_id": f"{provider_name}-thread-{uuid.uuid4()}",
        "provider": provider_name,
        "from_email": account_email,
        "accepted": True,
        "to_email": to_email,
        "subject": subject,
        "attachment_count": len(attachments) if attachments else 0,
        "attachment_ids": [],
    }
