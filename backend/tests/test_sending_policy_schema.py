"""Offline tests for SendingPolicyUpdate validation (no DB, no network, 0 tokens)."""

import pytest
from pydantic import ValidationError

from app.schemas.sending_policy import SendingPolicyUpdate


def test_valid_partial_update():
    u = SendingPolicyUpdate(daily_cap=10, window_start="08:30")
    assert u.model_dump(exclude_unset=True) == {"daily_cap": 10, "window_start": "08:30"}


def test_normalizes_hhmm_padding():
    u = SendingPolicyUpdate(window_start="9:5")
    assert u.window_start == "09:05"


@pytest.mark.parametrize("bad_time", ["25:00", "12:60", "not-a-time", "12", "12:00:00"])
def test_rejects_bad_hhmm(bad_time):
    with pytest.raises(ValidationError):
        SendingPolicyUpdate(window_start=bad_time)


def test_rejects_inverted_window():
    with pytest.raises(ValidationError, match="before"):
        SendingPolicyUpdate(window_start="13:00", window_end="09:00")


def test_accepts_equal_window_is_rejected():
    # An empty window (start == end) admits no sends — reject rather than silently disable sending.
    with pytest.raises(ValidationError, match="before"):
        SendingPolicyUpdate(window_start="09:00", window_end="09:00")


def test_window_order_only_checked_when_both_present():
    # Partial updates (only one side) are validated against the merged row at the API layer,
    # not here — the schema alone can't know the other side's current value.
    u = SendingPolicyUpdate(window_start="09:00")
    assert u.window_start == "09:00"
    assert u.window_end is None


@pytest.mark.parametrize("bad_days", ["", "xx,yy", "mondey", ","])
def test_rejects_days_with_no_valid_tokens(bad_days):
    with pytest.raises(ValidationError, match="no valid weekday"):
        SendingPolicyUpdate(send_days_first_touch=bad_days)


def test_accepts_days_with_at_least_one_valid_token():
    u = SendingPolicyUpdate(send_days_first_touch="mon,garbage")
    assert u.send_days_first_touch == "mon,garbage"


@pytest.mark.parametrize("field", ["daily_cap", "hourly_cap", "min_gap_minutes", "follow_up_after_business_days", "max_touches"])
def test_rejects_non_positive_caps(field):
    with pytest.raises(ValidationError, match="positive"):
        SendingPolicyUpdate(**{field: 0})
    with pytest.raises(ValidationError, match="positive"):
        SendingPolicyUpdate(**{field: -1})


def test_gap_jitter_allows_zero_but_not_negative():
    u = SendingPolicyUpdate(gap_jitter_minutes=0)
    assert u.gap_jitter_minutes == 0
    with pytest.raises(ValidationError):
        SendingPolicyUpdate(gap_jitter_minutes=-1)


def test_rejects_unknown_timezone():
    with pytest.raises(ValidationError, match="unknown timezone"):
        SendingPolicyUpdate(timezone="Not/AZone")


def test_accepts_valid_timezone():
    u = SendingPolicyUpdate(timezone="Asia/Nicosia")
    assert u.timezone == "Asia/Nicosia"


def test_rejects_incomplete_warmup_ramp():
    with pytest.raises(ValidationError, match="missing keys"):
        SendingPolicyUpdate(warmup_ramp_json={"start": 5})


def test_rejects_warmup_ramp_bad_started_on():
    with pytest.raises(ValidationError, match="started_on"):
        SendingPolicyUpdate(
            warmup_ramp_json={"start": 5, "step_per_week": 5, "cap": 25, "started_on": "not-a-date"},
        )


def test_rejects_warmup_ramp_non_positive_start_or_cap():
    with pytest.raises(ValidationError, match="positive"):
        SendingPolicyUpdate(
            warmup_ramp_json={"start": 0, "step_per_week": 5, "cap": 25, "started_on": "2026-07-08"},
        )


def test_accepts_valid_warmup_ramp():
    ramp = {"start": 5, "step_per_week": 5, "cap": 25, "started_on": "2026-07-08"}
    u = SendingPolicyUpdate(warmup_ramp_json=ramp)
    assert u.warmup_ramp_json == ramp


def test_enabled_toggle():
    assert SendingPolicyUpdate(enabled=False).enabled is False
    assert SendingPolicyUpdate(enabled=True).enabled is True
