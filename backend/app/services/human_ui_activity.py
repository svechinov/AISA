"""Short one-liners for the Human UI Activity panel — drained on GET workspace-lite / workspace-tick."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, attributes

from app.models.run import Run

_PENDING_KEY = "_human_ui_activity_pending"
_ONCE_KEY = "_human_ui_activity_once"
_MAX_PENDING = 120


def push_human_ui_activity(db: Session, run_id: int, text: str) -> None:
    """Append a line for the Activity panel; persisted with the same transaction as the caller (flush only)."""
    text = (text or "").strip()
    if not text:
        return
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return
    cj = dict(run.context_json or {})
    pending = cj.get(_PENDING_KEY)
    if not isinstance(pending, list):
        pending = []
    pending.append({"id": str(uuid.uuid4()), "text": text})
    if len(pending) > _MAX_PENDING:
        pending = pending[-_MAX_PENDING:]
    cj[_PENDING_KEY] = pending
    run.context_json = cj
    attributes.flag_modified(run, "context_json")
    db.flush()


def push_human_ui_activity_once(db: Session, run_id: int, once_id: str, text: str) -> None:
    """Append one line only the first time ``once_id`` is used for this run (flag kept after drain)."""
    text = (text or "").strip()
    once_id = (once_id or "").strip()
    if not text or not once_id:
        return
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return
    cj = dict(run.context_json or {})
    once = cj.get(_ONCE_KEY)
    if not isinstance(once, dict):
        once = {}
    if once.get(once_id):
        return
    once[once_id] = True
    cj[_ONCE_KEY] = once
    pending = cj.get(_PENDING_KEY)
    if not isinstance(pending, list):
        pending = []
    pending.append({"id": str(uuid.uuid4()), "text": text})
    if len(pending) > _MAX_PENDING:
        pending = pending[-_MAX_PENDING:]
    cj[_PENDING_KEY] = pending
    run.context_json = cj
    attributes.flag_modified(run, "context_json")
    db.flush()


def drain_human_ui_activity_pending(db: Session, run: Run) -> list[dict[str, Any]]:
    """Pop all pending lines for this run (one delivery to the client) and commit."""
    cj = dict(run.context_json or {})
    if _PENDING_KEY not in cj:
        return []
    raw = cj.pop(_PENDING_KEY)
    run.context_json = cj
    attributes.flag_modified(run, "context_json")
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            ttxt = str(item.get("text") or "").strip()
            if not ttxt:
                continue
            if not tid:
                tid = str(uuid.uuid4())
            out.append({"id": tid, "text": ttxt})
    db.commit()
    return out
