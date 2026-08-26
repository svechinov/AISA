"""Operational dashboard: one call that answers "what's the sending engine doing right now?" —
worker status, today's pace against caps, the queue, suppression size, and what needs a human.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.email_draft import EmailDraft
from app.models.follow_up_task import FollowUpTask
from app.models.send_queue import STATE_HELD, STATE_QUEUED, STATE_RELEASING
from app.models.system_setting import SystemSetting
from app.repositories.run_repo import get_run
from app.repositories.send_metrics_repo import count_sent_since
from app.repositories.send_queue_repo import is_paused, list_items
from app.repositories.suppression_repo import count_suppression
from app.services.sending_gates import effective_daily_cap, local_day_start_utc
from app.services.sending_policy_resolver import resolve_policy_for_run
from app.services.sending_scheduler import LAST_TICK_SETTING_KEY
from app.api.sending import _queue_item_to_dict

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/summary")
def ops_summary_route(run_id: int | None = Query(None), db: Session = Depends(get_db)):
    now_utc = datetime.utcnow()
    run = get_run(db, run_id) if run_id is not None else None
    # B-547: без run_id (или ран не найден) — прежнее поведение, дефолтная политика.
    policy, policy_source, persona = resolve_policy_for_run(db, run)

    # --- Worker ---
    worker_interval = int(getattr(settings, "SEND_QUEUE_INTERVAL_SECONDS", 0) or 0)
    last_tick_row = db.query(SystemSetting).filter(SystemSetting.key == LAST_TICK_SETTING_KEY).first()
    worker = {
        "enabled": worker_interval > 0,
        "interval_seconds": worker_interval,
        "paused": is_paused(db),
        "last_tick_at": last_tick_row.value if last_tick_row else None,
    }

    # --- Today (only meaningful with a policy configured) ---
    today: dict = {
        "policy_configured": policy is not None,
        # B-547: какой политикой на самом деле объясняется картина ниже — ран персоны или дефолт.
        "policy_source": policy_source,
        "persona_slug": getattr(persona, "slug", None),
        "persona_name": getattr(persona, "display_name", None),
        "run_id": run.id if run is not None else None,
    }
    if policy is not None:
        day_start = local_day_start_utc(now_utc, ZoneInfo(policy.timezone))
        sent_today = count_sent_since(db, day_start, policy.mailbox_email)
        cap_today = effective_daily_cap(int(policy.daily_cap), policy.warmup_ramp_json, date.today())
        # Only genuinely upcoming slots — a queued item with not_before in the past is overdue
        # (worker off/paused/behind), not "next up", and would be a confusing "past slot" on the card.
        # B-547 follow-up (code review afe4e2d): slots belong to the SAME mailbox as the rest of
        # this `today` block — a queued item from another mailbox is not "next up" for this policy.
        policy_mailbox = (policy.mailbox_email or "").strip().lower()
        next_slots = [
            item.not_before.isoformat()
            for item in list_items(db, states=(STATE_QUEUED,))
            if item.not_before is not None
            and item.not_before >= now_utc
            and (item.mailbox_email or "").strip().lower() == policy_mailbox
        ][:3]
        today.update(
            {
                "mailbox_email": policy.mailbox_email,
                "sent_today": sent_today,
                "daily_cap": cap_today,
                "window_start": policy.window_start,
                "window_end": policy.window_end,
                "timezone": policy.timezone,
                "send_days_first_touch": policy.send_days_first_touch,
                "send_days_follow_up": policy.send_days_follow_up,
                "next_slots": next_slots,
            },
        )

    # --- Queue ---
    all_active = list_items(db, states=(STATE_QUEUED, STATE_HELD, STATE_RELEASING))
    counts_by_state: dict[str, int] = {}
    for item in all_active:
        counts_by_state[item.state] = counts_by_state.get(item.state, 0) + 1
    held_items = [_queue_item_to_dict(i) for i in all_active if i.state == STATE_HELD]

    # --- Requires a human decision ---
    pending_drafts = (
        db.query(EmailDraft.id).filter(EmailDraft.review_status == "pending").count()
    )
    open_follow_ups_by_type: dict[str, int] = dict(
        db.query(FollowUpTask.task_type, func.count(FollowUpTask.id))
        .filter(FollowUpTask.status == "open")
        .group_by(FollowUpTask.task_type)
        .all(),
    )

    # --- Suppression ---
    suppression_count = count_suppression(db)

    # --- Gmail sync ---
    gmail_sync = {
        "interval_seconds": int(getattr(settings, "GMAIL_SYNC_INTERVAL_SECONDS", 0) or 0),
        "configured": bool((getattr(settings, "GMAIL_SEND_AS_EMAIL", "") or "").strip()),
    }

    return {
        "worker": worker,
        "today": today,
        "queue": {
            "counts_by_state": counts_by_state,
            "held": held_items,
        },
        "requires_decision": {
            "pending_drafts": pending_drafts,
            "open_follow_ups_by_type": open_follow_ups_by_type,
        },
        "suppression_count": suppression_count,
        "gmail_sync": gmail_sync,
    }
