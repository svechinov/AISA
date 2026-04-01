"""Stable identity for contacts when email is missing — avoids duplicate rows for the same person."""

from __future__ import annotations

import re
from typing import Any


def _norm_ws(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _strip_site(url: str | None) -> str:
    u = _norm_ws(url)
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.strip("/").rstrip("/")


def contact_identity_key_from_dict(contact: dict[str, Any] | None) -> str | None:
    """One key per natural person when email is absent or unusable for merge."""
    if not isinstance(contact, dict):
        return None
    name = _norm_ws(contact.get("name"))
    company = _norm_ws(contact.get("company"))
    site = _strip_site(contact.get("website"))
    if not name and not company and not site:
        return None
    return f"{name}\x1f{company}\x1f{site}"


def contact_identity_key_from_row(
    *,
    name: str | None,
    company: str | None,
    website: str | None,
) -> str | None:
    return contact_identity_key_from_dict(
        {"name": name, "company": company, "website": website},
    )
