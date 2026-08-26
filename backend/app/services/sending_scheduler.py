"""The send-queue worker: releases due, gate-passing drafts one at a time.

Runs on a background loop (see main.py lifespan). Each tick:
  - abort early if globally paused (kill switch);
  - recover any items stuck in `releasing` (a crash/restart mid-send);
  - take due items (not_before <= now, state=queued), oldest slot first;
  - for each: re-fetch draft + contact + policy, verify the address, run every gate;
      pass          -> send via the same send_one_draft used by the manual path, mark item sent;
      transient fail -> RESCHEDULE to the next valid slot (window/caps/company dialog) — never stuck;
      permanent fail -> park held with the reason (not-sendable, suppression, dead address).

One send per tick keeps min-gap/hourly pacing honest without extra bookkeeping — the next due item
waits for the following tick and re-checks the gap gate against the send that just happened.
"""

from __future__ import annotations

import logging
import threading
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.email_event import EmailEvent
from app.models.send_queue import STATE_CANCELED, STATE_HELD, STATE_SENT
from app.models.system_setting import SystemSetting
from app.repositories.contact_repo import get_contact
from app.repositories.email_draft_repo import get_email_draft
from app.repositories.sending_policy_repo import get_default_policy, get_policy_for_mailbox
from app.repositories.send_queue_repo import (
    claim_item,
    count_active_items_for_run,
    count_sent_items_for_run,
    due_items,
    is_paused,
    list_rescheduled_today,
    reschedule_item,
    reset_stale_releasing,
    set_state,
)
from app.services.email_sender import send_one_draft
from app.services.email_verification_service import DEAD, verify_and_apply_for_contact
from app.services.outreach_notify import notify
from app.services.send_queue_service import next_slot_from
from app.services.sending_gates import evaluate_gates

_log = logging.getLogger(__name__)

_STALE_RELEASING_MINUTES = 30
#: system_settings key the ops dashboard reads to show "worker last ran at" (app/api/ops.py).
LAST_TICK_SETTING_KEY = "send_queue_last_tick"

#: system_settings key: local (policy-TZ) calendar date the daily send digest last fired for.
DIGEST_LAST_DATE_KEY = "outreach_daily_digest_last_date"
#: Local hour (policy TZ) at/after which the daily digest may fire; override via env.
_DEFAULT_DIGEST_HOUR = 21

#: Cheap in-process guard: the background loop and the manual POST /sending/queue/tick endpoint
#: run in separate threads and can otherwise both scan due_items() in the same instant. claim_item
#: (send_queue_repo.py) already makes a double SEND impossible at the DB level — this lock just
#: avoids the wasted duplicate gate-evaluation work of two ticks racing each other pointlessly.
_tick_lock = threading.Lock()


def run_queue_tick(db: Session, now_utc: datetime | None = None, max_sends: int = 1) -> dict:
    """Process due items; send up to max_sends. Returns a small summary (for logs/tests)."""
    if not _tick_lock.acquire(blocking=False):
        return {
            "paused": False, "sent": 0, "held": 0, "rescheduled": 0, "checked": 0,
            "skipped": "another tick is already running",
        }
    try:
        return _run_queue_tick_locked(db, now_utc, max_sends)
    finally:
        _tick_lock.release()


def _run_queue_tick_locked(db: Session, now_utc: datetime | None, max_sends: int) -> dict:
    now_utc = now_utc or datetime.utcnow()
    if is_paused(db):
        return {"paused": True, "sent": 0, "held": 0, "rescheduled": 0, "checked": 0}

    # Recover items left in-flight by a crash/restart between mark-releasing and send.
    reset_stale_releasing(db, now_utc - timedelta(minutes=_STALE_RELEASING_MINUTES))

    checked = sent = held = rescheduled = canceled = 0
    for item in due_items(db, now_utc):
        checked += 1
        draft = get_email_draft(db, item.draft_id)
        if draft is None:
            set_state(db, item, STATE_HELD, hold_reason="draft missing")
            held += 1
            continue
        contact = get_contact(db, item.contact_id) if item.contact_id else None
        policy = get_policy_for_mailbox(db, item.mailbox_email)
        if policy is None or not policy.enabled:
            set_state(db, item, STATE_HELD, hold_reason="mailbox policy missing or disabled")
            held += 1
            continue

        # Verify the address at release (TTL-cached; only hits DNS/provider when stale). Dead → cancel.
        if contact is not None and verify_and_apply_for_contact(db, contact) == DEAD:
            set_state(db, item, STATE_CANCELED, hold_reason="address dead (verification)")
            canceled += 1
            continue

        result = evaluate_gates(
            db,
            draft=draft,
            contact=contact,
            policy=policy,
            touch_number=item.touch_number,
            now_utc=now_utc,
        )
        if not result.ok:
            if result.transient:
                base = result.retry_at or now_utc
                new_slot = next_slot_from(policy, item.touch_number, base)
                reschedule_item(db, item, new_slot, reason=result.reason)
                rescheduled += 1
            else:
                set_state(db, item, STATE_HELD, hold_reason=result.reason)
                held += 1
            continue

        # Gate passed — release. Claim it atomically first: a concurrent tick (e.g. the manual
        # POST /sending/queue/tick endpoint, which runs in its own thread) may have already taken
        # this same due item between due_items() above and here. A lost claim is not an error —
        # just skip it, the other tick owns it now.
        if not claim_item(db, item.id):
            continue
        try:
            send_result = send_one_draft(db, item.draft_id)
        except Exception as e:  # noqa: BLE001 — a send crash must not leave the item stuck releasing
            _log.exception("send_one_draft raised for draft %s", item.draft_id)
            set_state(db, item, STATE_HELD, hold_reason=f"send crashed: {e}")
            held += 1
            continue
        if send_result.get("status") == "sent":
            set_state(db, item, STATE_SENT)
            sent += 1
            _notify_item_sent(db, item)
            if count_active_items_for_run(db, item.run_id) == 0:
                notify(f"🚀 Run #{item.run_id}: отправка завершена")
        else:
            set_state(db, item, STATE_HELD, hold_reason=f"send failed: {send_result.get('error')}")
            held += 1

        if sent >= max_sends:
            break

    return {
        "paused": False, "sent": sent, "held": held,
        "rescheduled": rescheduled, "canceled": canceled, "checked": checked,
    }


def _upsert_setting(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
        db.add(row)
    db.commit()


def _record_last_tick(db: Session, now_utc: datetime) -> None:
    _upsert_setting(db, LAST_TICK_SETTING_KEY, now_utc.isoformat())


def _notify_item_sent(db: Session, item) -> None:
    """Per-send Telegram ping into the AI-Biz-OS topic: who it went to and run progress (N/M)."""
    contact = get_contact(db, item.contact_id) if item.contact_id else None
    contact_ref = (contact.email if contact and contact.email else None) or f"contact #{item.contact_id}"
    sent_for_run = count_sent_items_for_run(db, item.run_id)
    total = sent_for_run + count_active_items_for_run(db, item.run_id)
    notify(f"📤 Run #{item.run_id}: письмо ушло → {contact_ref} ({sent_for_run}/{total})")


def _ru_plural_letters(n: int) -> str:
    """'письмо' / 'письма' / 'писем' for a Russian count."""
    tail = abs(n) % 100
    if 11 <= tail <= 14:
        return "писем"
    last = tail % 10
    if last == 1:
        return "письмо"
    if 2 <= last <= 4:
        return "письма"
    return "писем"


def _digest_timezone(db: Session) -> ZoneInfo:
    policy = get_default_policy(db)
    name = (policy.timezone if policy and policy.timezone else "") or "Asia/Nicosia"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Asia/Nicosia")


def maybe_send_daily_digest(db: Session, now_utc: datetime | None = None) -> dict:
    """End-of-day summary of what shipped, at most once per policy-TZ calendar day.

    Fires after ``OUTREACH_DIGEST_HOUR_LOCAL`` (default 21:00) local time. Counts ``sent``
    email events since local midnight, grouped by run, plus items that were due today but got
    transient-rescheduled instead of shipping (B-026 — the "digest said 4/10 but only 3 went
    out" trap: a gate silently pushed one to a later slot). Silent on days nothing went out and
    nothing was rescheduled, but still marks the day done so it doesn't re-scan every tick.
    Never raises out of the tick.
    """
    now_utc = now_utc or datetime.utcnow()
    try:
        digest_hour = int(os.environ.get("OUTREACH_DIGEST_HOUR_LOCAL", _DEFAULT_DIGEST_HOUR))
    except (TypeError, ValueError):
        digest_hour = _DEFAULT_DIGEST_HOUR

    tz = _digest_timezone(db)
    now_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    today_local = now_local.date().isoformat()

    row = db.query(SystemSetting).filter(SystemSetting.key == DIGEST_LAST_DATE_KEY).first()
    if row is not None and (row.value or "") == today_local:
        return {"sent": False, "reason": "already today"}
    if now_local.hour < digest_hour:
        return {"sent": False, "reason": "before digest hour"}

    since_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = since_local.astimezone(timezone.utc).replace(tzinfo=None)
    per_run = (
        db.query(EmailEvent.run_id, func.count(EmailEvent.id))
        .filter(EmailEvent.event_type == "sent", EmailEvent.created_at >= since_utc)
        .group_by(EmailEvent.run_id)
        .all()
    )
    total = sum(int(c) for _, c in per_run)
    rescheduled = list_rescheduled_today(db, since_utc, now_utc)

    # Mark the day done regardless — the sending window has closed by digest hour.
    _upsert_setting(db, DIGEST_LAST_DATE_KEY, today_local)
    if total == 0 and not rescheduled:
        return {"sent": False, "reason": "nothing sent"}

    lines = []
    if total:
        lines.append(f"📊 Итог дня {now_local.strftime('%d.%m')}: отправлено {total} {_ru_plural_letters(total)}")
        for run_id, count in sorted(per_run, key=lambda r: (-int(r[1]), int(r[0]))):
            lines.append(f"• Run #{run_id} — {int(count)}")
    if rescheduled:
        lines.append(f"⏸ Запланировано на сегодня, но не ушло: {len(rescheduled)}")
        for item in rescheduled:
            contact = get_contact(db, item.contact_id) if item.contact_id else None
            contact_ref = (contact.email if contact and contact.email else None) or f"contact #{item.contact_id}"
            lines.append(f"• Run #{item.run_id}, черновик #{item.draft_id} → {contact_ref} — {item.last_reschedule_reason}")
    notify("\n".join(lines))
    return {"sent": True, "total": total, "rescheduled": len(rescheduled)}


def run_queue_tick_in_thread() -> None:
    """Own DB session per tick (mirrors the Gmail-sync worker). Also runs the once-daily follow-up
    cadence and the once-daily send digest."""
    db = SessionLocal()
    try:
        from app.services.followup_cadence_service import maybe_run_daily_cadence

        now_utc = datetime.utcnow()
        maybe_run_daily_cadence(db)
        run_queue_tick(db)
        # Digest runs outside run_queue_tick so a paused queue still gets its end-of-day summary.
        try:
            maybe_send_daily_digest(db, now_utc)
        except Exception:
            _log.exception("daily send digest failed")
        _record_last_tick(db, now_utc)
    except Exception:
        _log.exception("send-queue tick failed")
    finally:
        db.close()
