"""Split reminder source_json / output_json into typed columns; API merges columns + JSON extras."""

from __future__ import annotations

from typing import Any


def _opt_str(v: Any, max_len: int) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:max_len]


def split_reminder_source_for_storage(source: dict | None) -> tuple[dict[str, Any], dict]:
    """Returns (column kwargs, remainder for source_json)."""
    rest = dict(source or {})
    cols: dict[str, Any] = {}
    if "source" in rest:
        cols["source_kind"] = _opt_str(rest.pop("source"), 50)
    if "task_type" in rest:
        cols["task_type_snapshot"] = _opt_str(rest.pop("task_type"), 80)
    rest.pop("follow_up_task_id", None)
    rest.pop("thread_id", None)
    return cols, rest


def split_reminder_output_for_storage(output: dict | None) -> tuple[dict[str, Any], dict]:
    """Returns (column kwargs, remainder for output_json)."""
    rest = dict(output or {})
    cols: dict[str, Any] = {}
    if "triggered_by" in rest:
        cols["output_triggered_by"] = _opt_str(rest.pop("triggered_by"), 80)
    return cols, rest


def apply_reminder_output_full(reminder: Any, output: dict | None) -> None:
    """Replace output from a full merged dict (status updates, scheduler)."""
    if output is None:
        return
    cols, rem = split_reminder_output_for_storage(output)
    if "output_triggered_by" in cols:
        reminder.output_triggered_by = cols["output_triggered_by"]
    else:
        reminder.output_triggered_by = None
    reminder.output_json = rem if rem else {}


def effective_source_json(reminder: Any) -> dict:
    extra = dict(getattr(reminder, "source_json", None) or {})
    base: dict[str, Any] = {}
    sk = getattr(reminder, "source_kind", None)
    if sk:
        base["source"] = sk
    tt = getattr(reminder, "task_type_snapshot", None)
    if tt:
        base["task_type"] = tt
    fut = getattr(reminder, "follow_up_task_id", None)
    if fut is not None:
        base["follow_up_task_id"] = fut
    tid = getattr(reminder, "thread_id", None)
    if tid is not None:
        base["thread_id"] = tid
    return {**extra, **base}


def effective_output_json(reminder: Any) -> dict:
    extra = dict(getattr(reminder, "output_json", None) or {})
    base: dict[str, Any] = {}
    tb = getattr(reminder, "output_triggered_by", None)
    if tb:
        base["triggered_by"] = tb
    return {**extra, **base}


def normalize_reminder_typed_columns(reminder: Any) -> bool:
    """Move canonical keys from JSON into columns; set JSON to extras only. Returns True if row changed."""
    src_merged = effective_source_json(reminder)
    out_merged = effective_output_json(reminder)
    cols_s, rem_s = split_reminder_source_for_storage(src_merged)
    cols_o, rem_o = split_reminder_output_for_storage(out_merged)
    before = (
        dict(getattr(reminder, "source_json", None) or {}),
        dict(getattr(reminder, "output_json", None) or {}),
        getattr(reminder, "source_kind", None),
        getattr(reminder, "task_type_snapshot", None),
        getattr(reminder, "output_triggered_by", None),
    )
    for k, v in cols_s.items():
        setattr(reminder, k, v)
    for k, v in cols_o.items():
        setattr(reminder, k, v)
    reminder.source_json = rem_s if rem_s else {}
    reminder.output_json = rem_o if rem_o else {}
    after = (
        dict(reminder.source_json or {}),
        dict(reminder.output_json or {}),
        getattr(reminder, "source_kind", None),
        getattr(reminder, "task_type_snapshot", None),
        getattr(reminder, "output_triggered_by", None),
    )
    return before != after
