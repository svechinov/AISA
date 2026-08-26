"""LLM: classify whether a full email thread indicates bounce vs dead mailbox vs normal (on-demand UI)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.email_message_repo import list_email_messages_by_thread
from app.repositories.email_thread_repo import get_email_thread
from app.services.inbound_delivery_llm_service import _normalize_llm_delivery_out
from app.services.llm_gateway import complete_prompt_json_object, llm_configured

_log = logging.getLogger(__name__)

_MAX_TRANSCRIPT_CHARS = 14_000
_MAX_BODY_PER_MESSAGE = 4_000


def build_thread_transcript_for_delivery_llm(db: Session, thread_id: int) -> str | None:
    if not get_email_thread(db, thread_id):
        return None
    msgs = list_email_messages_by_thread(db, thread_id)
    if not msgs:
        return "(no messages in thread)"
    parts: list[str] = []
    used = 0
    for i, m in enumerate(msgs):
        dir_label = (m.direction or "").strip().upper() or "UNKNOWN"
        header = (
            f"[{dir_label}] Subject: {m.subject or ''}\n"
            f"From: {m.from_email or ''} To: {m.to_email or ''}\n"
        )
        body = (m.body or "")[:_MAX_BODY_PER_MESSAGE]
        chunk = header + body + "\n---\n"
        if used + len(chunk) > _MAX_TRANSCRIPT_CHARS:
            parts.append(f"\n(truncated: {len(msgs) - i} older messages omitted)\n")
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


def classify_thread_transcript_delivery_llm(transcript: str) -> dict[str, Any] | None:
    if not llm_configured():
        return None
    excerpt = (transcript or "")[:_MAX_TRANSCRIPT_CHARS]
    prompt = f"""You review a complete email THREAD (our outbound outreach and all replies) in a B2B tool.

Decide whether the thread indicates a problem with **delivery** of our message to the recipient's mailbox:
- bounce: temporary failure, deferral, generic rejection, blocked, DSN-style notices, "could not deliver" without a clear "user does not exist".
- dead_mailbox: permanent failure — user unknown, address invalid, mailbox does not exist, 5.1.1 style "no such user".
- none: normal human replies (interested, not interested, OOO), questions, or no delivery-failure signal.
- unclear: genuinely ambiguous.

Use the whole thread; outbound may be first or interleaved. Return ONLY valid JSON (no markdown) with keys:
- "delivery_issue": one of "none", "bounce", "dead_mailbox", "unclear"
- "confidence": one of "low", "medium", "high"
- "reason": short English phrase (max 200 chars) pointing to what in the thread supports your choice

Thread transcript (oldest messages first within the excerpt):
{excerpt}
"""
    try:
        raw = complete_prompt_json_object(prompt, task_kind="thread_delivery_classify")
        if not isinstance(raw, dict):
            return None
        return _normalize_llm_delivery_out(raw)
    except Exception:
        _log.warning("thread delivery LLM classification failed", exc_info=True)
        return None


def analyze_thread_delivery_llm(db: Session, thread_id: int) -> dict[str, Any]:
    """For API: never raises for LLM failure — returns `error` key."""
    transcript = build_thread_transcript_for_delivery_llm(db, thread_id)
    if transcript is None:
        return {
            "delivery_issue": "unclear",
            "confidence": "low",
            "reason": "",
            "error": "thread_not_found",
        }
    if not llm_configured():
        return {
            "delivery_issue": "unclear",
            "confidence": "low",
            "reason": "",
            "error": "llm_not_configured",
        }
    llm = classify_thread_transcript_delivery_llm(transcript)
    if not llm:
        return {
            "delivery_issue": "unclear",
            "confidence": "low",
            "reason": "",
            "error": "llm_failed",
        }
    return {
        "delivery_issue": llm.get("delivery_issue", "unclear"),
        "confidence": llm.get("confidence", "low"),
        "reason": llm.get("reason", ""),
        "error": None,
    }
