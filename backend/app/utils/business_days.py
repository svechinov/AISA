"""Business-day arithmetic (Mon–Fri), timezone-naive. Used for follow-up cadence and the
one-company-one-dialog gate. Holidays are not modeled — weekends only."""

from __future__ import annotations

from datetime import datetime, timedelta


def is_business_day(d: datetime) -> bool:
    return d.weekday() < 5  # Mon=0 .. Fri=4


def add_business_days(start: datetime, n: int) -> datetime:
    """Return the datetime n business days after `start` (n >= 0), preserving time-of-day."""
    if n < 0:
        raise ValueError("n must be >= 0")
    result = start
    remaining = n
    while remaining > 0:
        result = result + timedelta(days=1)
        if is_business_day(result):
            remaining -= 1
    return result


def subtract_business_days(start: datetime, n: int) -> datetime:
    """Return the datetime n business days before `start` (n >= 0), preserving time-of-day."""
    if n < 0:
        raise ValueError("n must be >= 0")
    result = start
    remaining = n
    while remaining > 0:
        result = result - timedelta(days=1)
        if is_business_day(result):
            remaining -= 1
    return result
