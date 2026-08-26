"""LLM-assisted classification for inbound messages that look like DSN / bounces (subset only)."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import get_email_draft
from app.services.email_tracking_service import register_manual_bounce, register_manual_dead_mailbox
from app.services.llm_gateway import complete_prompt_json_object, llm_configured

_log = logging.getLogger(__name__)

_LLM_CONFIDENT = frozenset({"medium", "high"})


def inbound_message_should_run_llm_delivery_check(
    *,
    from_email: str | None,
    subject: str,
    body: str,
) -> bool:
    """Narrow gate: only messages that plausibly relate to delivery failure."""
    blob = f"{from_email or ''} {subject or ''} {(body or '')[:6000]}".lower()
    if any(
        x in blob
        for x in (
            "mailer-daemon",
            "mailer daemon",
            "postmaster@",
            "mail delivery subsystem",
            "mail delivery system",
        )
    ):
        return True
    if any(
        x in blob
        for x in (
            "undeliverable",
            "undelivered mail",
            "returned to sender",
            "delivery status",
            "failure notice",
            "message blocked",
            "could not be delivered",
        )
    ):
        return True
    if re.search(r"\b5\.\d{1,2}\.\d{1,2}\b", blob):
        return True
    return False


def _normalize_llm_delivery_out(raw: dict[str, Any]) -> dict[str, Any]:
    issue = str(raw.get("delivery_issue") or raw.get("delivery") or "unclear").strip().lower()
    if issue in ("bounce", "bounced", "soft_bounce"):
        issue = "bounce"
    elif issue in ("dead_mailbox", "hard_bounce", "invalid_mailbox", "user_unknown"):
        issue = "dead_mailbox"
    elif issue in ("none", "no", "human", "normal", "ok"):
        issue = "none"
    else:
        issue = "unclear"
    conf = str(raw.get("confidence") or "low").strip().lower()
    if conf not in ("low", "medium", "high"):
        conf = "low"
    reason = str(raw.get("reason") or "")[:500]
    return {"delivery_issue": issue, "confidence": conf, "reason": reason}


def classify_inbound_delivery_llm(
    *,
    from_email: str | None,
    subject: str,
    body_excerpt: str,
) -> dict[str, Any] | None:
    """Returns normalized dict or None if LLM unavailable or failed."""
    if not llm_configured():
        return None
    excerpt = (body_excerpt or "")[:8000]
    prompt = f"""You classify ONE inbound email for a B2B outreach tool.

Decide if this message is primarily:
- A delivery failure / DSN / bounce notification about a message we sent (bounce: recipient server refused or delayed),
- A "dead mailbox" / user unknown / address invalid style permanent failure (dead_mailbox),
- Or neither (normal human reply, auto-reply out of office, marketing, or unrelated) → none.

Return ONLY valid JSON (no markdown) with keys:
- "delivery_issue": one of "none", "bounce", "dead_mailbox", "unclear"
- "confidence": one of "low", "medium", "high"
- "reason": short English phrase (max 200 chars)

From: {from_email or "(unknown)"}
Subject: {subject or "(empty)"}
Body (excerpt):
{excerpt}
"""
    try:
        raw = complete_prompt_json_object(prompt, task_kind="inbound_delivery_classify")
        if not isinstance(raw, dict):
            return None
        return _normalize_llm_delivery_out(raw)
    except Exception:
        _log.warning("inbound delivery LLM classification failed", exc_info=True)
        return None


def maybe_apply_inbound_delivery_llm_after_message(
    db: Session,
    *,
    draft_id: int | None,
    from_email: str | None,
    subject: str,
    body: str,
    gmail_message_id: str | None = None,
) -> dict[str, Any]:
    """
    If heuristics + LLM agree (medium/high), apply manual bounce/dead tracking for the outbound draft.
    Only for sent drafts. Safe no-op if gates fail.
    """
    out: dict[str, Any] = {"applied": False, "skipped_reason": None}
    if not draft_id:
        out["skipped_reason"] = "no_draft_id"
        return out
    if not inbound_message_should_run_llm_delivery_check(
        from_email=from_email,
        subject=subject,
        body=body,
    ):
        out["skipped_reason"] = "heuristic_gate"
        return out
    draft = get_email_draft(db, draft_id)
    if not draft or draft.status != "sent":
        out["skipped_reason"] = "draft_not_sent"
        return out
    llm = classify_inbound_delivery_llm(
        from_email=from_email,
        subject=subject,
        body_excerpt=body,
    )
    if not llm:
        out["skipped_reason"] = "llm_unavailable"
        return out
    issue = llm.get("delivery_issue")
    conf = llm.get("confidence")
    if conf not in _LLM_CONFIDENT:
        out["skipped_reason"] = "low_confidence"
        out["llm"] = llm
        return out
    if issue not in ("bounce", "dead_mailbox"):
        out["skipped_reason"] = "llm_none_or_unclear"
        out["llm"] = llm
        return out
    payload = {
        "source": "llm_inbound_delivery",
        "gmail_message_id": gmail_message_id,
        "llm_reason": llm.get("reason"),
        "llm_delivery_issue": issue,
    }
    err = llm.get("reason") or f"LLM: {issue}"
    try:
        if issue == "dead_mailbox":
            r = register_manual_dead_mailbox(
                db,
                draft_id,
                payload_json=payload,
                error_message=err[:220],
            )
        else:
            r = register_manual_bounce(
                db,
                draft_id,
                payload_json=payload,
                error_message=err[:220],
            )
        out["applied"] = not r.get("skipped")
        out["result"] = r
        out["llm"] = llm
    except ValueError as e:
        out["skipped_reason"] = str(e)
        out["llm"] = llm
    return out
