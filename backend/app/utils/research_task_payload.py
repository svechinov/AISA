"""Research task input/output in entity_json_kv; legacy columns cleared on first read."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RESEARCH_INPUT, SCOPE_RESEARCH_OUTPUT
from app.models.research_task import ResearchTask
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_research_input_json(db: Session, task: ResearchTask) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_RESEARCH_INPUT,
        task.id,
        task.input_json,
        clear_legacy=lambda: setattr(task, "input_json", {}),
    )


def effective_research_output_json(db: Session, task: ResearchTask) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_RESEARCH_OUTPUT,
        task.id,
        task.output_json,
        clear_legacy=lambda: setattr(task, "output_json", {}),
    )


def persist_research_input(db: Session, task: ResearchTask, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_RESEARCH_INPUT, task.id, data or None)
    task.input_json = {}


def persist_research_output(db: Session, task: ResearchTask, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_RESEARCH_OUTPUT, task.id, data or None)
    task.output_json = {}
