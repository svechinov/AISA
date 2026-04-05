"""Follow-up task source/output in entity_json_kv; legacy columns cleared on first read."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_FOLLOW_UP_OUTPUT, SCOPE_FOLLOW_UP_SOURCE
from app.models.follow_up_task import FollowUpTask
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_follow_up_source_json(db: Session, task: FollowUpTask) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_FOLLOW_UP_SOURCE,
        task.id,
        task.source_json,
        clear_legacy=lambda: setattr(task, "source_json", {}),
    )


def effective_follow_up_output_json(db: Session, task: FollowUpTask) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_FOLLOW_UP_OUTPUT,
        task.id,
        task.output_json,
        clear_legacy=lambda: setattr(task, "output_json", {}),
    )


def persist_follow_up_source(db: Session, task: FollowUpTask, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_FOLLOW_UP_SOURCE, task.id, data or None)
    task.source_json = {}


def persist_follow_up_output(db: Session, task: FollowUpTask, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_FOLLOW_UP_OUTPUT, task.id, data or None)
    task.output_json = {}
