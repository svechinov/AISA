"""Tiny env-var parsing helpers — one copy instead of a per-worker reimplementation.

Note: process env is the source of truth here; backend/.env reaches os.environ via
env_bootstrap.load_env_from_file() at startup (standalone scripts must call it themselves).
"""

from __future__ import annotations

import os


def env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    """Integer env var with a default; malformed values fall back, min_value clamps."""
    raw = os.environ.get(name, "").strip()
    try:
        n = int(raw) if raw else default
    except ValueError:
        n = default
    if min_value is not None and n < min_value:
        n = default
    return n


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
