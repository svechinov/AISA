"""Validation for editing a SendingPolicy from the ops UI. Rejects values that would silently
break the worker (empty day sets, malformed HH:MM, inverted windows, non-positive caps)."""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator

from app.services.sending_gates import parse_hhmm, parse_send_days


def _validate_hhmm(value: str) -> str:
    v = (value or "").strip()
    parts = v.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"expected HH:MM, got {value!r}")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"expected HH:MM in range, got {value!r}")
    return f"{hh:02d}:{mm:02d}"


def _validate_days(value: str) -> str:
    if not parse_send_days(value):
        raise ValueError(f"no valid weekday tokens in {value!r} (use mon,tue,wed,thu,fri,sat,sun)")
    return value


class SendingPolicyUpdate(BaseModel):
    """All fields optional — PATCH applies only what's provided."""

    daily_cap: int | None = None
    hourly_cap: int | None = None
    min_gap_minutes: int | None = None
    gap_jitter_minutes: int | None = None
    send_days_first_touch: str | None = None
    send_days_follow_up: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    timezone: str | None = None
    warmup_ramp_json: dict | None = None
    follow_up_after_business_days: int | None = None
    max_touches: int | None = None
    enabled: bool | None = None

    @field_validator("daily_cap", "hourly_cap", "min_gap_minutes", "follow_up_after_business_days", "max_touches")
    @classmethod
    def _positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("must be a positive integer")
        return v

    @field_validator("gap_jitter_minutes")
    @classmethod
    def _non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("send_days_first_touch", "send_days_follow_up")
    @classmethod
    def _days(cls, v: str | None) -> str | None:
        return _validate_days(v) if v is not None else v

    @field_validator("window_start", "window_end")
    @classmethod
    def _hhmm(cls, v: str | None) -> str | None:
        return _validate_hhmm(v) if v is not None else v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"unknown timezone {v!r}") from e
        return v

    @field_validator("warmup_ramp_json")
    @classmethod
    def _ramp(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        required = {"start", "step_per_week", "cap", "started_on"}
        missing = required - set(v)
        if missing:
            raise ValueError(f"warmup_ramp_json missing keys: {sorted(missing)}")
        if not (isinstance(v["start"], int) and isinstance(v["cap"], int) and v["start"] > 0 and v["cap"] > 0):
            raise ValueError("warmup_ramp_json.start and .cap must be positive integers")
        from datetime import date

        try:
            date.fromisoformat(str(v["started_on"]))
        except ValueError as e:
            raise ValueError("warmup_ramp_json.started_on must be YYYY-MM-DD") from e
        return v

    @model_validator(mode="after")
    def _window_order(self) -> "SendingPolicyUpdate":
        # Only checkable when both are provided in this request — field validators above have
        # already normalized both to a valid HH:MM by the time this runs, so parsing can't fail.
        # A partial update that changes only one side is checked against the merged row by the route.
        if self.window_start is not None and self.window_end is not None:
            from datetime import time as _time

            start = parse_hhmm(self.window_start, _time(0, 0))
            end = parse_hhmm(self.window_end, _time(0, 0))
            if start >= end:
                raise ValueError("window_start must be before window_end")
        return self
