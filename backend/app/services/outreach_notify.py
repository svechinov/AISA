"""Fire-and-forget Telegram notifications for the outreach engine.

Wraps ``telegram_notify.send`` in a daemon thread so a notification can never block or crash
the engine — a dead token, network blip, or unconfigured chat is a warning log, not a failure.
"""

from __future__ import annotations

import logging
import threading

from app.services import telegram_notify

_log = logging.getLogger(__name__)

_PROJECT = "AI-Biz-OS"


def notify(text: str) -> None:
    """Send ``text`` to the AI-Biz-OS Telegram topic in the background. Never raises."""

    def _send() -> None:
        try:
            telegram_notify.send(_PROJECT, text, timeout=5.0)
        except Exception:
            _log.exception("outreach_notify: failed to send Telegram notification")

    threading.Thread(target=_send, daemon=True).start()
