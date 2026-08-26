"""Shared email normalization — the `(email or "").strip().lower()` idiom was copy-pasted across
suppression, verification, and cadence code; small drifts there let a suppressed/dead address slip
through under a differently-cased or padded form. One place to change it."""

from __future__ import annotations


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def email_domain(email: str | None) -> str:
    e = normalize_email(email)
    return e.rsplit("@", 1)[-1] if "@" in e else ""
