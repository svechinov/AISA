"""Telegram inbound bridge (v1): long-poll getUpdates, file incoming messages per project.

Runs as a background loop on the always-on server (see ``_telegram_poller_loop`` in ``app.main``),
gated by ``TELEGRAM_POLLER_ENABLED``. Long-polling only — no inbound ports.

v1 is a *dumb inbox*: text/doc/voice from the owner (DM or the configured supergroup) is routed by
``message_thread_id`` to a project and written as a Markdown file (+ attachments) under
``<data>/telegram_inbox/<project>/``. A local ``scripts/pull_telegram_inbox.py`` step later syncs
those into the Obsidian vault ``_inbox`` folders. No LLM, no system-changing commands — just capture.

Security: only messages whose ``chat.id`` is the owner DM or the configured group are processed;
everything else is ignored. The getUpdates offset is persisted in ``system_settings`` so restarts
never reprocess old messages.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.config import settings
from app.db import SessionLocal
from app.models.system_setting import SystemSetting
from app.services import telegram_notify
from app.services.telegram_notify import TELEGRAM_API

_log = logging.getLogger(__name__)

OFFSET_KEY = "telegram_update_offset"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9А-Яа-яЁё._-]+")


# --------------------------------------------------------------------------- paths / offset

def inbox_dir() -> Path:
    """Base dir for inbox files. TELEGRAM_INBOX_DIR override, else <data>/telegram_inbox."""
    raw = (settings.TELEGRAM_INBOX_DIR or "").strip()
    if raw:
        return Path(raw)
    dotenv = os.environ.get("AI_BIZ_OS_DOTENV", "").strip()
    if dotenv:
        return Path(dotenv).resolve().parent / "telegram_inbox"
    from app.services.env_bootstrap import BACKEND_ROOT

    return BACKEND_ROOT / "data" / "telegram_inbox"


def _load_offset(db) -> int:
    row = db.query(SystemSetting).filter(SystemSetting.key == OFFSET_KEY).first()
    if not row or not (row.value or "").strip():
        return 0
    try:
        return int(row.value.strip())
    except ValueError:
        return 0


def _save_offset(db, value: int) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == OFFSET_KEY).first()
    if row is None:
        db.add(SystemSetting(key=OFFSET_KEY, value=str(value)))
    else:
        row.value = str(value)
        db.add(row)
    db.commit()


# --------------------------------------------------------------------------- pure helpers

def _safe(name: str, *, fallback: str = "item") -> str:
    cleaned = _SAFE_NAME_RE.sub("-", (name or "").strip()).strip("-._")
    return cleaned or fallback


def classify_message(msg: dict) -> tuple[str, str, list[dict]]:
    """Return (kind, text, attachments) for a Telegram message.

    ``attachments`` items: ``{"file_id": str, "suggested_name": str}``. ``text`` carries the message
    text or a media caption. ``kind`` ∈ {text, voice, audio, document, photo, other}.
    """
    caption = (msg.get("caption") or "").strip()

    if "text" in msg:
        return "text", (msg.get("text") or "").strip(), []

    if "voice" in msg:
        v = msg["voice"]
        uid = v.get("file_unique_id") or v.get("file_id", "voice")
        return "voice", caption, [{"file_id": v["file_id"], "suggested_name": f"voice-{uid}.ogg"}]

    if "audio" in msg:
        a = msg["audio"]
        name = a.get("file_name") or f"audio-{a.get('file_unique_id', a.get('file_id'))}.mp3"
        return "audio", caption, [{"file_id": a["file_id"], "suggested_name": name}]

    if "document" in msg:
        d = msg["document"]
        name = d.get("file_name") or f"document-{d.get('file_unique_id', d.get('file_id'))}"
        return "document", caption, [{"file_id": d["file_id"], "suggested_name": name}]

    if "photo" in msg and msg["photo"]:
        p = msg["photo"][-1]  # largest size
        uid = p.get("file_unique_id") or p.get("file_id", "photo")
        return "photo", caption, [{"file_id": p["file_id"], "suggested_name": f"photo-{uid}.jpg"}]

    return "other", caption, []


def _sender_label(msg: dict) -> str:
    frm = msg.get("from") or {}
    name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x).strip()
    uname = frm.get("username")
    if uname:
        name = f"{name} (@{uname})" if name else f"@{uname}"
    return name or str(frm.get("id") or "unknown")


def build_inbox_markdown(
    *,
    project: str,
    sender: str,
    kind: str,
    text: str,
    received_iso: str,
    attachments: list[str],
    chat_id: int | str | None = None,
) -> str:
    """Markdown inbox record with frontmatter (mirrors the vault doc convention).

    ``chat_id``: needed for General — the group's General topic and the owner's private DM both
    land in the same Общее/ folder with no message_thread_id, so it's the only way general_agent
    (a separate service reading these files) can reply to the chat the question actually came from.
    """
    lines = [
        "---",
        f"project: {project}",
        f"from: {sender}",
        f"kind: {kind}",
        f"received: {received_iso}",
        "source: telegram",
    ]
    if chat_id is not None:
        lines.append(f"chat_id: {chat_id}")
    if attachments:
        lines.append("attachments:")
        lines.extend(f"  - {a}" for a in attachments)
    lines.append("---")
    lines.append("")
    if text:
        lines.append(text)
    elif attachments:
        lines.append(f"({kind}: " + ", ".join(attachments) + ")")
    else:
        lines.append(f"({kind}, без текста)")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- Telegram I/O

def _get_updates(token: str, offset: int, timeout: int) -> list[dict]:
    url = f"{TELEGRAM_API}/bot{token}/getUpdates"
    params: dict = {"timeout": timeout, "allowed_updates": json.dumps(["message"])}
    if offset:
        params["offset"] = offset
    try:
        resp = httpx.get(url, params=params, timeout=timeout + 10)
    except httpx.HTTPError as exc:
        _log.warning("telegram getUpdates transport error: %s", exc)
        return []
    try:
        data = resp.json()
    except ValueError:
        _log.warning("telegram getUpdates bad JSON: HTTP %s", resp.status_code)
        return []
    if not data.get("ok"):
        _log.warning("telegram getUpdates not ok: %s", str(data)[:300])
        return []
    return data.get("result", []) or []


OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"


def transcribe_audio(path: Path) -> str | None:
    """Transcribe a saved audio file via OpenAI Whisper. Returns text, or None on any failure.

    Requires OPENAI_API_KEY. OGG/Opus (Telegram voice) is an accepted input format, so no ffmpeg
    conversion is needed. Never raises — the poller falls back to storing the raw audio.
    """
    if not settings.TELEGRAM_VOICE_TRANSCRIBE:
        return None
    key = (settings.OPENAI_API_KEY or "").strip()
    if not key:
        return None
    data: dict = {"model": (settings.VOICE_TRANSCRIBE_MODEL or "whisper-1").strip(), "response_format": "text"}
    lang = (settings.VOICE_TRANSCRIBE_LANGUAGE or "").strip()
    if lang:
        data["language"] = lang
    try:
        with open(path, "rb") as fh:
            resp = httpx.post(
                OPENAI_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {key}"},
                data=data,
                files={"file": (path.name, fh, "audio/ogg")},
                timeout=120,
            )
    except (httpx.HTTPError, OSError) as exc:
        _log.warning("telegram voice transcription error: %s", exc)
        return None
    if resp.status_code != 200:
        _log.warning("telegram voice transcription HTTP %s: %s", resp.status_code, resp.text[:300])
        return None
    text = (resp.text or "").strip()  # response_format=text → raw transcript
    return text or None


def _download_attachment(token: str, file_id: str, dest_dir: Path, suggested_name: str) -> str | None:
    """getFile → download into dest_dir. Returns the saved filename, or None on failure."""
    try:
        meta = httpx.get(
            f"{TELEGRAM_API}/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=30,
        ).json()
    except (httpx.HTTPError, ValueError) as exc:
        _log.warning("telegram getFile error: %s", exc)
        return None
    if not meta.get("ok"):
        _log.warning("telegram getFile not ok: %s", str(meta)[:200])
        return None
    file_path = (meta.get("result") or {}).get("file_path")
    if not file_path:
        return None
    name = _safe(suggested_name, fallback=Path(file_path).name or "file")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    try:
        with httpx.stream("GET", f"{TELEGRAM_API}/file/bot{token}/{file_path}", timeout=120) as r:
            if r.status_code != 200:
                _log.warning("telegram file download HTTP %s", r.status_code)
                return None
            with open(dest, "wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
    except (httpx.HTTPError, OSError) as exc:
        _log.warning("telegram file download error: %s", exc)
        return None
    return name


# --------------------------------------------------------------------------- processing

def _allowed_chat_ids() -> set[str]:
    ids: set[str] = set()
    for raw in (settings.TELEGRAM_GROUP_CHAT_ID, settings.TELEGRAM_OWNER_CHAT_ID):
        v = (raw or "").strip()
        if v:
            ids.add(v)
    return ids


def _process_update(update: dict, token: str, topics: dict[str, int]) -> None:
    msg = update.get("message")
    if not isinstance(msg, dict):
        return

    chat = msg.get("chat") or {}
    if str(chat.get("id")) not in _allowed_chat_ids():
        _log.info("telegram: ignoring message from unauthorized chat %s", chat.get("id"))
        return

    thread_id = msg.get("message_thread_id")
    project = telegram_notify.project_for_thread(thread_id, topics)
    kind, text, attachments = classify_message(msg)
    received = datetime.now(timezone.utc)
    received_iso = received.strftime("%Y-%m-%dT%H:%M:%SZ")

    base = inbox_dir() / _safe(project, fallback="Общее")
    stamp = received.strftime("%Y-%m-%d-%H%M%S")
    update_id = update.get("update_id", "0")

    saved_names: list[str] = []
    for att in attachments:
        name = _download_attachment(token, att["file_id"], base / "attachments", att["suggested_name"])
        if name:
            saved_names.append(name)

    # Voice/audio → transcribe to text so the body is readable (and the ack echoes it).
    transcript: str | None = None
    if kind in ("voice", "audio") and saved_names:
        transcript = transcribe_audio(base / "attachments" / saved_names[0])
        if transcript:
            text = f"{text}\n\n{transcript}".strip() if text else transcript

    md = build_inbox_markdown(
        project=project,
        sender=_sender_label(msg),
        kind=kind,
        text=text,
        received_iso=received_iso,
        attachments=saved_names,
        chat_id=chat.get("id"),
    )
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{stamp}-{update_id}.md").write_text(md, encoding="utf-8")

    # Append to a flat JSONL log for quick auditing / the pull step.
    log_entry = {
        "received": received_iso,
        "project": project,
        "thread_id": thread_id,
        "kind": kind,
        "update_id": update_id,
        "attachments": saved_names,
        "text_preview": (text or "")[:200],
    }
    inbox_root = inbox_dir()
    inbox_root.mkdir(parents=True, exist_ok=True)
    with open(inbox_root / "log.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # Acknowledge back into the same topic — except General, which is a live dialog: the
    # general_agent service watches these same files and replies with an actual answer shortly;
    # a "✅ Принял" ack there would just be noise ahead of the real response.
    if project == telegram_notify.GENERAL_PROJECT:
        return

    if kind in ("voice", "audio") and transcript:
        snippet = transcript if len(transcript) <= 200 else transcript[:200] + "…"
        ack_text = f"✅ Принял в inbox проекта «{project}» (голос → текст):\n{snippet}"
    else:
        kind_ru = {
            "text": "текст",
            "voice": "голос (расшифровать не удалось, сохранил аудио)",
            "audio": "аудио",
            "document": "документ",
            "photo": "фото",
            "other": "сообщение",
        }.get(kind, kind)
        ack_text = f"✅ Принял в inbox проекта «{project}»: {kind_ru}."
    ack = {"chat_id": chat.get("id"), "text": ack_text}
    if thread_id is not None:
        ack["message_thread_id"] = thread_id
    telegram_notify.post("sendMessage", ack, token=token)


def run_poll_tick_in_thread() -> None:
    """One long-poll cycle: fetch updates, process authorized ones, advance the offset.

    Blocking (long-poll up to TELEGRAM_POLL_TIMEOUT_SEC) — call via ``asyncio.to_thread``.
    """
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return

    db = SessionLocal()
    try:
        offset = _load_offset(db)
    finally:
        db.close()

    updates = _get_updates(token, offset + 1 if offset else 0, int(settings.TELEGRAM_POLL_TIMEOUT_SEC))
    if not updates:
        return

    topics = telegram_notify.parse_topics()
    max_id = offset
    for update in updates:
        uid = int(update.get("update_id", 0))
        try:
            _process_update(update, token, topics)
        except Exception:  # noqa: BLE001 — one bad message must not stall the whole feed
            _log.exception("telegram: failed to process update %s", uid)
        max_id = max(max_id, uid)

    if max_id > offset:
        db = SessionLocal()
        try:
            _save_offset(db, max_id)
        finally:
            db.close()
