"""Step input/output: entity_json_kv is canonical; legacy columns are cleared on first read."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_STEP_INPUT, SCOPE_STEP_OUTPUT
from app.models.step import Step
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_step_input_json(db: Session, step: Step) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_STEP_INPUT,
        step.id,
        step.input_json,
        clear_legacy=lambda: setattr(step, "input_json", {}),
    )


def effective_step_output_json(db: Session, step: Step) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_STEP_OUTPUT,
        step.id,
        step.output_json,
        clear_legacy=lambda: setattr(step, "output_json", {}),
    )


def persist_step_input(db: Session, step: Step, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_STEP_INPUT, step.id, data or None)
    step.input_json = {}


def persist_step_output(db: Session, step: Step, data: dict[str, Any]) -> None:
    replace_kv_dict(db, SCOPE_STEP_OUTPUT, step.id, data or None)
    step.output_json = {}
