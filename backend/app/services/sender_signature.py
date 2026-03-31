"""Append per-run HTML signature to outbound email bodies (draft body is stored without it)."""

from __future__ import annotations

from app.services.outbound_email_body import (
    append_signature_html_after,
    normalize_draft_body_for_email_html,
)


def append_signature_to_body(body: str | None, signature_html: str | None) -> str:
    base_raw = str(body or "").strip()
    base = normalize_draft_body_for_email_html(body) if base_raw else ""
    return append_signature_html_after(base, signature_html)
