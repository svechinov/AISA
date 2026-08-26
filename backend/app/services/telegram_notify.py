"""Telegram notifications + shared topic registry for the comms layer.

One bot, one supergroup with forum topics. Each project maps to a ``message_thread_id`` so
notifications land in the right topic and inbound messages can be routed back to a project
(the poller reuses ``parse_topics`` / ``project_for_thread`` here).

Outbound only (``sendMessage``); no ports opened. Reads token + registry from ``settings``.
Sync by design — call via ``asyncio.to_thread`` from async contexts (same discipline as the
send-queue/gmail workers in ``app.main``).
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

_log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

#: Fallback project name for the "general" topic / DMs with no thread.
GENERAL_PROJECT = "Общее"


def _token() -> str:
    return (settings.TELEGRAM_BOT_TOKEN or "").strip()


def parse_topics(raw: str | None = None) -> dict[str, int]:
    """Parse ``"AI-Biz-OS:2,Content:5"`` into ``{"AI-Biz-OS": 2, "Content": 5}``.

    Original casing is preserved (used for inbox folder names). Malformed entries are skipped.
    """
    if raw is None:
        raw = settings.TELEGRAM_TOPICS or ""
    out: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, tid = part.rpartition(":")
        name = name.strip()
        tid = tid.strip()
        if not name or not tid:
            continue
        try:
            out[name] = int(tid)
        except ValueError:
            continue
    return out


def thread_for_project(project: str | None, topics: dict[str, int] | None = None) -> int | None:
    """message_thread_id for a project (case-insensitive), or None if unmapped."""
    if not project:
        return None
    topics = topics if topics is not None else parse_topics()
    want = project.strip().lower()
    for name, tid in topics.items():
        if name.lower() == want:
            return tid
    return None


def project_for_thread(
    thread_id: int | None,
    topics: dict[str, int] | None = None,
    *,
    default: str = GENERAL_PROJECT,
) -> str:
    """Reverse lookup thread_id → project name; ``default`` for DMs/unmapped topics."""
    topics = topics if topics is not None else parse_topics()
    if thread_id is not None:
        for name, tid in topics.items():
            if tid == thread_id:
                return name
    return default


def post(method: str, payload: dict, *, token: str | None = None, timeout: float = 15.0) -> bool:
    """POST to the Bot API; True only on HTTP 200 with ``{"ok": true}``. Never raises."""
    token = token or _token()
    if not token:
        _log.warning("telegram: no bot token configured; skipping %s", method)
        return False
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    try:
        resp = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as exc:
        _log.warning("telegram %s transport error: %s", method, exc)
        return False
    try:
        ok = resp.status_code == 200 and bool(resp.json().get("ok"))
    except ValueError:
        ok = False
    if not ok:
        _log.warning("telegram %s failed: HTTP %s %s", method, resp.status_code, resp.text[:300])
    return ok


def send(
    project: str | None,
    text: str,
    *,
    parse_mode: str | None = None,
    timeout: float = 15.0,
) -> bool:
    """Send a notification for ``project`` into its topic; fall back to the owner DM.

    Routing:
    - project mapped to a topic AND a group is configured → group + message_thread_id;
    - project is None AND a group is configured → group "general" (no thread);
    - otherwise → owner DM.
    """
    if not _token():
        _log.warning("telegram_notify.send: no token; message dropped")
        return False

    topics = parse_topics()
    thread = thread_for_project(project, topics)
    group = (settings.TELEGRAM_GROUP_CHAT_ID or "").strip()
    owner = (settings.TELEGRAM_OWNER_CHAT_ID or "").strip()

    payload: dict = {"text": text, "disable_web_page_preview": True}
    if group and (thread is not None or project is None):
        payload["chat_id"] = group
        if thread is not None:
            payload["message_thread_id"] = thread
    elif owner:
        payload["chat_id"] = owner
    else:
        _log.warning("telegram_notify.send: no group/owner chat configured; message dropped")
        return False

    if parse_mode:
        payload["parse_mode"] = parse_mode
    return post("sendMessage", payload, timeout=timeout)
