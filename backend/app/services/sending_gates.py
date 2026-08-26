"""Send-queue safety gates: the checks a queued draft must pass before the worker releases it.

Two layers:
  - pure predicates (window / caps / warm-up ramp) — no DB, fully unit-testable;
  - ``evaluate_gates`` — gathers DB state and applies every gate in order, returning the first failure.

A failing gate never sends: the worker parks the item as ``held`` with the returned reason, visible in
the queue. Nothing is sent silently and nothing is lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.email_draft import EmailDraft
from app.repositories.send_metrics_repo import count_sent_since, last_sent_at
from app.services.email_sender import validate_outbound_draft_sendable
from app.utils.business_days import subtract_business_days

_WEEKDAY_ABBR = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class GateResult:
    ok: bool
    reason: str | None = None
    #: A transient failure (window/caps/company dialog) should be RESCHEDULED, not parked as held.
    #: Only permanent failures (not-sendable, suppression, confirmed-dead address) become held.
    transient: bool = False
    #: Earliest instant (naive UTC) the worker should retry a transient failure. None → next window.
    retry_at: datetime | None = None


# --------------------------------------------------------------------------- pure predicates

def parse_send_days(spec: str | None) -> set[int]:
    """"tue,wed,thu" -> {1,2,3}. Unknown tokens ignored; empty spec -> empty set (nothing allowed)."""
    out: set[int] = set()
    for tok in (spec or "").split(","):
        k = tok.strip().lower()
        if k in _WEEKDAY_ABBR:
            out.add(_WEEKDAY_ABBR[k])
    return out


def parse_hhmm(spec: str | None, default: time) -> time:
    try:
        hh, mm = (spec or "").strip().split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return default


def is_within_window(
    now_local: datetime,
    window_start: str,
    window_end: str,
    allowed_weekdays: set[int],
) -> bool:
    if now_local.weekday() not in allowed_weekdays:
        return False
    start = parse_hhmm(window_start, time(9, 0))
    end = parse_hhmm(window_end, time(12, 30))
    return start <= now_local.time() <= end


def warmup_daily_cap(ramp: dict | None, today: date) -> int | None:
    """Current cap from a warm-up ramp, or None if no valid ramp is configured.

    ramp = {"start": int, "step_per_week": int, "cap": int, "started_on": "YYYY-MM-DD"}.
    Cap grows by step_per_week each full week since started_on, clamped to cap.
    """
    if not isinstance(ramp, dict):
        return None
    try:
        start = int(ramp["start"])
        step = int(ramp.get("step_per_week", 0))
        ceiling = int(ramp["cap"])
        started_on = date.fromisoformat(str(ramp["started_on"]))
    except (KeyError, ValueError, TypeError):
        return None
    weeks_elapsed = max(0, (today - started_on).days // 7)
    return min(ceiling, start + step * weeks_elapsed)


def effective_daily_cap(daily_cap: int, ramp: dict | None, today: date) -> int:
    """During warm-up the ramp caps below daily_cap; once ramped past it, daily_cap is the ceiling."""
    ramp_cap = warmup_daily_cap(ramp, today)
    if ramp_cap is None:
        return daily_cap
    return min(daily_cap, ramp_cap)


def caps_ok(
    sent_today: int,
    sent_this_hour: int,
    minutes_since_last: float | None,
    daily_cap: int,
    hourly_cap: int,
    min_gap_minutes: int,
) -> GateResult:
    if sent_today >= daily_cap:
        return GateResult(False, f"daily cap reached ({sent_today}/{daily_cap})")
    if sent_this_hour >= hourly_cap:
        return GateResult(False, f"hourly cap reached ({sent_this_hour}/{hourly_cap})")
    if minutes_since_last is not None and minutes_since_last < min_gap_minutes:
        return GateResult(False, f"min gap not elapsed ({int(minutes_since_last)}/{min_gap_minutes} min)")
    return GateResult(True)


# --------------------------------------------------------------------------- DB-backed coordinator

def local_day_start_utc(now_utc: datetime, tz: ZoneInfo) -> datetime:
    """UTC instant of local-midnight (start of today in policy tz) for per-calendar-day counting.

    Public: also used by the ops dashboard (app/api/ops.py) to compute "sent today" consistently
    with the gate's own daily-cap check.
    """
    now_local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    local_midnight = datetime.combine(now_local.date(), time(0, 0), tzinfo=tz)
    return local_midnight.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _company_has_active_touch(
    db: Session,
    company: str | None,
    exclude_contact_id: int | None,
    within_since: datetime,
) -> bool:
    """Another contact at the same company with a sent, un-replied touch newer than the cutoff.

    Enforces one live dialog per company: a second contact waits until the first has gone silent.
    Same-contact follow-ups are excluded (touch 2 to the same person is fine).
    """
    c = (company or "").strip().lower()
    if not c:
        return False
    q = db.query(EmailDraft.id).filter(
        func.lower(func.trim(EmailDraft.company)) == c,
        EmailDraft.status == "sent",
        EmailDraft.tracking_status != "replied",
        EmailDraft.sent_at.isnot(None),
        EmailDraft.sent_at >= within_since,
    )
    if exclude_contact_id is not None:
        q = q.filter(EmailDraft.contact_id != exclude_contact_id)
    return q.first() is not None


def evaluate_gates(
    db: Session,
    *,
    draft,
    contact,
    policy,
    touch_number: int,
    now_utc: datetime | None = None,
) -> GateResult:
    now_utc = now_utc or datetime.utcnow()

    # 1. Draft is sendable: review status, recipient, run open, has a signature, not suppressed,
    #    not a confirmed-dead address (same chokepoint as the manual send path — one source of
    #    truth). Catch-all/unknown verification does NOT block here.
    try:
        validate_outbound_draft_sendable(db, draft)
    except ValueError as e:
        return GateResult(False, str(e))

    # 2. One live dialog per company (only for a first touch; follow-ups stay with the same contact).
    #    Transient: retry tomorrow — the other dialog may go silent past the window by then.
    if touch_number <= 1:
        cutoff = subtract_business_days(now_utc, int(policy.follow_up_after_business_days))
        company = getattr(draft, "company", None) or getattr(contact, "company", None)
        if _company_has_active_touch(db, company, getattr(draft, "contact_id", None), cutoff):
            return GateResult(
                False, "company already has an active dialog",
                transient=True, retry_at=now_utc + timedelta(days=1),
            )

    # 3. Volume caps (daily with warm-up ramp, hourly, min gap) from email_events. All transient.
    mailbox = policy.mailbox_email
    day_start = local_day_start_utc(now_utc, ZoneInfo(policy.timezone))
    sent_today = count_sent_since(db, day_start, mailbox)
    sent_this_hour = count_sent_since(db, now_utc - timedelta(hours=1), mailbox)
    last_at = last_sent_at(db, mailbox)
    minutes_since_last = ((now_utc - last_at).total_seconds() / 60.0) if last_at else None
    daily = effective_daily_cap(int(policy.daily_cap), policy.warmup_ramp_json, now_utc.date())
    cap_result = caps_ok(
        sent_today,
        sent_this_hour,
        minutes_since_last,
        daily,
        int(policy.hourly_cap),
        int(policy.min_gap_minutes),
    )
    if not cap_result.ok:
        # Retry hint by which limit tripped: day → tomorrow, hour → +1h, gap → remaining gap.
        if sent_today >= daily:
            retry_at = now_utc + timedelta(days=1)
        elif sent_this_hour >= int(policy.hourly_cap):
            retry_at = now_utc + timedelta(hours=1)
        else:
            remaining = int(policy.min_gap_minutes) - (minutes_since_last or 0)
            retry_at = now_utc + timedelta(minutes=max(1, remaining))
        return GateResult(False, cap_result.reason, transient=True, retry_at=retry_at)

    # 4. Inside the allowed send window (weekday by touch type + local hours). Transient → next window.
    days_spec = policy.send_days_first_touch if touch_number <= 1 else policy.send_days_follow_up
    now_local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(policy.timezone))
    if not is_within_window(now_local, policy.window_start, policy.window_end, parse_send_days(days_spec)):
        return GateResult(False, "outside send window", transient=True, retry_at=now_utc)

    return GateResult(True)
