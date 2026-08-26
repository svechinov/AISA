"""Pure-function tests for the send-queue gates and business-day helpers (no DB, 0 tokens)."""

from datetime import datetime, date

from app.services.sending_gates import (
    caps_ok,
    effective_daily_cap,
    is_within_window,
    parse_send_days,
    warmup_daily_cap,
)
from app.utils.business_days import add_business_days, subtract_business_days


def test_parse_send_days():
    assert parse_send_days("tue,wed,thu") == {1, 2, 3}
    assert parse_send_days("MON, fri ,  sun") == {0, 4, 6}
    assert parse_send_days("") == set()
    assert parse_send_days("garbage,tue") == {1}


def test_is_within_window_weekday_and_hours():
    allowed = parse_send_days("tue,wed,thu")  # {1,2,3}
    wed_morning = datetime(2026, 7, 8, 10, 0)   # Wednesday
    wed_afternoon = datetime(2026, 7, 8, 15, 0)
    mon_morning = datetime(2026, 7, 6, 10, 0)   # Monday — not allowed
    assert is_within_window(wed_morning, "09:00", "12:30", allowed) is True
    assert is_within_window(wed_afternoon, "09:00", "12:30", allowed) is False  # after window
    assert is_within_window(mon_morning, "09:00", "12:30", allowed) is False    # wrong weekday


def test_is_within_window_edges_inclusive():
    allowed = {1, 2, 3}
    assert is_within_window(datetime(2026, 7, 8, 9, 0), "09:00", "12:30", allowed) is True
    assert is_within_window(datetime(2026, 7, 8, 12, 30), "09:00", "12:30", allowed) is True
    assert is_within_window(datetime(2026, 7, 8, 8, 59), "09:00", "12:30", allowed) is False


def test_warmup_daily_cap_ramps_and_clamps():
    ramp = {"start": 5, "step_per_week": 5, "cap": 25, "started_on": "2026-07-08"}
    assert warmup_daily_cap(ramp, date(2026, 7, 8)) == 5     # week 0
    assert warmup_daily_cap(ramp, date(2026, 7, 15)) == 10   # week 1
    assert warmup_daily_cap(ramp, date(2026, 7, 22)) == 15   # week 2
    assert warmup_daily_cap(ramp, date(2026, 9, 1)) == 25    # clamped at cap
    assert warmup_daily_cap(None, date(2026, 7, 8)) is None
    assert warmup_daily_cap({"bad": 1}, date(2026, 7, 8)) is None


def test_effective_daily_cap_prefers_lower_during_warmup():
    ramp = {"start": 5, "step_per_week": 5, "cap": 25, "started_on": "2026-07-08"}
    # daily_cap high, ramp low -> ramp wins early
    assert effective_daily_cap(50, ramp, date(2026, 7, 8)) == 5
    # once ramp exceeds daily_cap, daily_cap is the ceiling
    assert effective_daily_cap(10, ramp, date(2026, 9, 1)) == 10
    # no ramp -> daily_cap
    assert effective_daily_cap(7, None, date(2026, 7, 8)) == 7


def test_caps_ok_daily_hourly_gap():
    assert caps_ok(0, 0, None, 5, 2, 45).ok is True
    assert caps_ok(5, 0, 999, 5, 2, 45).ok is False        # daily reached
    assert caps_ok(2, 2, 999, 5, 2, 45).ok is False        # hourly reached
    assert caps_ok(1, 1, 10, 5, 2, 45).ok is False         # gap too short
    assert caps_ok(1, 1, 46, 5, 2, 45).ok is True          # gap satisfied
    assert caps_ok(0, 0, None, 5, 2, 45).reason is None


def test_next_slot_from_rolls_into_window():
    from types import SimpleNamespace
    from app.services.send_queue_service import next_slot_from

    policy = SimpleNamespace(
        send_days_first_touch="tue,wed,thu",
        send_days_follow_up="mon,tue,wed,thu",
        window_start="09:00",
        window_end="12:30",
        timezone="UTC",  # keep the test tz-stable
    )
    # A Monday 15:00 UTC first-touch base must roll forward to the next allowed day's window start.
    mon_afternoon = datetime(2026, 7, 6, 15, 0)  # Monday, outside window + wrong weekday
    slot = next_slot_from(policy, 1, mon_afternoon)
    assert slot.weekday() in {1, 2, 3}          # tue/wed/thu
    assert slot.strftime("%H:%M") == "09:00"     # rolled to window start
    assert slot > mon_afternoon

    # An in-window Wednesday base is kept as-is.
    wed_in = datetime(2026, 7, 8, 10, 0)
    assert next_slot_from(policy, 1, wed_in) == wed_in


def test_gate_result_transient_defaults():
    from app.services.sending_gates import GateResult

    assert GateResult(True).transient is False
    r = GateResult(False, "outside send window", transient=True)
    assert r.transient is True and r.ok is False


def test_business_days_skip_weekends():
    fri = datetime(2026, 7, 10, 10, 0)   # Friday
    # +1 business day from Friday -> Monday
    assert add_business_days(fri, 1).date() == date(2026, 7, 13)
    # +4 business days from Friday -> next Thursday
    assert add_business_days(fri, 4).date() == date(2026, 7, 16)
    # -4 business days from a Wednesday -> previous Thursday
    wed = datetime(2026, 7, 8, 10, 0)
    assert subtract_business_days(wed, 4).date() == date(2026, 7, 2)
    assert add_business_days(fri, 0) == fri
