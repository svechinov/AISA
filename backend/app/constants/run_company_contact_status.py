"""Allowed persisted values for ``run_companies.contact_status`` (relational column)."""

from __future__ import annotations

PERSISTED_CONTACT_STATUSES = frozenset(
    {"found", "none", "pending", "no_email", "llm_error"},
)
