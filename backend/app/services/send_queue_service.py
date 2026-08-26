"""Enqueue approved drafts and plan their send slots.

Slot planning spaces items after the current queue tail by (min_gap + jitter) and rolls each slot
forward into the next valid send window for its touch type. The runtime gates re-check everything at
release, so planning only needs to spread load into plausible windows — it is not the safety layer.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.send_queue import STATE_SENT, STATE_CANCELED
from app.repositories.send_queue_repo import (
    create_item,
    get_by_draft,
    latest_planned_not_before,
    revive_canceled_item,
)
from app.repositories.sending_policy_repo import get_default_policy, get_policy_for_mailbox
from app.services.sending_gates import parse_hhmm, parse_send_days

_log = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")


def _roll_to_window(base_utc: datetime, policy, allowed_days: set[int]) -> datetime:
    """Return the first valid in-window instant at/after base_utc, as naive UTC."""
    tz = ZoneInfo(policy.timezone)
    win_start = parse_hhmm(policy.window_start, time(9, 0))
    win_end = parse_hhmm(policy.window_end, time(12, 30))
    local = base_utc.replace(tzinfo=_UTC).astimezone(tz)

    for _ in range(21):  # at most ~3 weeks ahead; guards against an empty allowed-days set
        if local.weekday() in allowed_days:
            if local.time() < win_start:
                local = local.replace(hour=win_start.hour, minute=win_start.minute, second=0, microsecond=0)
                return local.astimezone(_UTC).replace(tzinfo=None)
            if local.time() <= win_end:
                return local.astimezone(_UTC).replace(tzinfo=None)
        # advance to next day's window start
        nxt = (local + timedelta(days=1)).replace(
            hour=win_start.hour, minute=win_start.minute, second=0, microsecond=0,
        )
        local = nxt
    # Fallback (misconfigured empty allowed-days): keep base so the item is at least visible/held.
    return base_utc


def next_slot_from(policy, touch_number: int, base_utc: datetime) -> datetime:
    """First valid send-window slot at/after base_utc, for this touch type. Used to reschedule
    an item whose gate failed transiently (window closed, cap hit, min-gap not elapsed)."""
    days_spec = policy.send_days_first_touch if touch_number <= 1 else policy.send_days_follow_up
    return _roll_to_window(base_utc, policy, parse_send_days(days_spec))


def plan_slot(db: Session, policy, touch_number: int, now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.utcnow()
    tail = latest_planned_not_before(db, policy.mailbox_email)
    if tail is None:
        base = now_utc
    else:
        gap = policy.min_gap_minutes + random.randint(0, max(0, policy.gap_jitter_minutes))
        base = max(now_utc, tail + timedelta(minutes=gap))
    days_spec = policy.send_days_first_touch if touch_number <= 1 else policy.send_days_follow_up
    return _roll_to_window(base, policy, parse_send_days(days_spec))


def _touch_number_for_draft(db: Session, draft) -> int:
    """Touch number = 1 + how many touches this contact has already been sent (single source of truth;
    the same rule the cadence uses). Address verification happens at release, not here."""
    contact_id = getattr(draft, "contact_id", None)
    if contact_id is None:
        return 1
    from app.models.email_draft import EmailDraft

    sent = (
        db.query(EmailDraft.id)
        .filter(EmailDraft.contact_id == contact_id, EmailDraft.status == "sent")
        .count()
    )
    return sent + 1


def _persona_mailbox_for_draft(db: Session, draft) -> str:
    """Mailbox of the persona that owns this draft's run (B-071). Empty string when it cannot be
    resolved — callers then keep the legacy default-policy behavior."""
    from app.repositories.run_repo import get_run
    from app.services.persona_service import get_run_persona

    run = get_run(db, getattr(draft, "run_id", None))
    if run is None:
        return ""
    try:
        persona = get_run_persona(db, run)
    except Exception:  # noqa: BLE001 — persona lookup must never break enqueue
        _log.exception("enqueue_draft: persona lookup failed for draft %s", draft.id)
        return ""
    return (getattr(persona, "primary_mailbox_email", None) or "").strip()


def enqueue_draft(db: Session, draft, touch_number: int | None = None, mailbox_email: str | None = None):
    """Idempotently add an approved draft to the send queue with a planned slot.

    Returns the queue item, or None if there is no sending policy or the draft is already sent.
    Safe to call from the approve hook: an active item is returned unchanged, a previously
    canceled item is revived (re-approve after cancel), and a sent item is left alone.
    Address verification is done by the worker at release, so approve stays fast.

    Mailbox routing (B-128): the queue item's mailbox_email wins over the run persona at send time
    (email_sender._resolve_send_mailbox), so an explicit persona run must not fall through to the
    default policy — that would sign the mail as Stepan and send it from Alexey's mailbox. Order:
    explicit mailbox_email -> the run persona's mailbox -> default policy (persona-less runs only).
    A persona whose mailbox has no policy row is NOT queued: sending it from the wrong identity is
    worse than leaving it approved-but-unqueued, which is visible in the queue view.
    """
    if (draft.status or "") == "sent":
        return None

    policy = get_policy_for_mailbox(db, mailbox_email) if mailbox_email else None
    if policy is None:
        persona_mailbox = _persona_mailbox_for_draft(db, draft)
        if persona_mailbox:
            policy = get_policy_for_mailbox(db, persona_mailbox)
            if policy is None:
                _log.warning(
                    "enqueue_draft: no sending policy for persona mailbox %s; draft %s not queued",
                    persona_mailbox, draft.id,
                )
                return None
        else:
            policy = get_default_policy(db)
    if policy is None:
        _log.info("enqueue_draft: no sending policy configured; draft %s not queued", draft.id)
        return None

    touch = touch_number if touch_number is not None else _touch_number_for_draft(db, draft)
    slot = plan_slot(db, policy, touch)

    existing = get_by_draft(db, draft.id)
    if existing is not None:
        if existing.state == STATE_SENT:
            return existing
        if existing.state == STATE_CANCELED:
            # Re-approve after cancel: revive the same row (UNIQUE(draft_id) forbids a second insert).
            return revive_canceled_item(db, existing, not_before=slot, touch_number=touch)
        return existing  # queued / held / releasing — leave as-is

    item = create_item(
        db,
        draft_id=draft.id,
        run_id=draft.run_id,
        contact_id=getattr(draft, "contact_id", None),
        mailbox_email=policy.mailbox_email,
        touch_number=touch,
        not_before=slot,
    )
    _log.info(
        "enqueue_draft: draft=%s touch=%s slot=%s mailbox=%s",
        draft.id, touch, slot.isoformat(), policy.mailbox_email,
    )
    return item
