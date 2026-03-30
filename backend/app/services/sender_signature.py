"""Append per-run HTML signature to outbound email bodies (draft body is stored without it)."""

from __future__ import annotations


def append_signature_to_body(body: str | None, signature_html: str | None) -> str:
    base = body or ""
    sig = (signature_html or "").strip()
    if not sig:
        return base
    base = base.rstrip()
    if not base:
        return sig
    if "<" in base or "<" in sig:
        return f"{base}\n<br><br>\n{sig}"
    return f"{base}\n\n{sig}"
