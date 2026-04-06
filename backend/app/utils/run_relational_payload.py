"""Runs: outreach context, input extras, master email variants — relational storage + legacy merge."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RUN_CONTEXT_EXTRA, SCOPE_RUN_INPUT
from app.models.run import Run
from app.models.run_master_email_variant import RunMasterEmailVariant
from app.models.run_outreach_context import RunOutreachContext
from app.services.run_context_service import coalesce_str, wrap_context
from app.utils.entity_kv_storage import get_kv_dict, replace_kv_dict


_CTX = ("offer", "target_entities", "target_roles", "goal", "tone", "notes")


def inner_from_context_json_blob(context_json: dict | None) -> dict[str, str]:
    raw = dict(context_json or {})
    nested = raw.get("context")
    if isinstance(nested, dict):
        return {k: coalesce_str(nested.get(k, "")) for k in _CTX}
    return {
        "offer": coalesce_str(raw.get("offer") or raw.get("product")),
        "target_entities": coalesce_str(raw.get("target_entities")),
        "target_roles": coalesce_str(raw.get("target_roles")),
        "goal": coalesce_str(raw.get("goal") or raw.get("outreach_goal")),
        "tone": coalesce_str(raw.get("tone")) or "Professional",
        "notes": coalesce_str(raw.get("notes") or raw.get("extra_context")),
    }


def upsert_run_outreach_context_row(db: Session, run_id: int, inner: dict[str, str]) -> RunOutreachContext:
    row = db.query(RunOutreachContext).filter(RunOutreachContext.run_id == run_id).first()
    if row is None:
        row = RunOutreachContext(run_id=run_id)
        db.add(row)
    row.offer = coalesce_str(inner.get("offer"))
    row.target_entities = coalesce_str(inner.get("target_entities"))
    row.target_roles = coalesce_str(inner.get("target_roles"))
    row.goal = coalesce_str(inner.get("goal"))
    row.tone = coalesce_str(inner.get("tone")) or "Professional"
    row.notes = coalesce_str(inner.get("notes"))
    return row


def persist_run_context_extras_from_blob(db: Session, run_id: int, context_json: dict | None) -> None:
    """Top-level keys except 'context' and '_human_ui' -> run_context_extra kv."""
    raw = dict(context_json or {})
    extras: dict[str, Any] = {}
    for k, v in raw.items():
        if k in ("context", "_human_ui"):
            continue
        extras[k] = v
    replace_kv_dict(db, SCOPE_RUN_CONTEXT_EXTRA, run_id, extras if extras else None)


def merge_run_context_json_blob_into_kv(db: Session, run_id: int, context_json: dict | None) -> None:
    """
    Fold legacy ``runs.context_json`` into ``entity_json_kv`` (merge with existing extras).
    Skips nested ``context`` (canonical copy lives in ``run_outreach_context``).
    Used before clearing the blob so saves never drop ``_human_ui`` or other extras.
    """
    raw = dict(context_json or {})
    if not raw:
        return
    existing = get_kv_dict(db, SCOPE_RUN_CONTEXT_EXTRA, run_id)
    merged: dict[str, Any] = dict(existing)
    for k, v in raw.items():
        if k == "context":
            continue
        merged[k] = v
    replace_kv_dict(db, SCOPE_RUN_CONTEXT_EXTRA, run_id, merged if merged else None)


def persist_run_input_from_blob(db: Session, run: Run, input_json: dict | None) -> None:
    ij = dict(input_json or {})
    goal = ij.pop("goal", None)
    replace_kv_dict(db, SCOPE_RUN_INPUT, run.id, ij if ij else None)
    run.input_goal = str(goal).strip() if goal is not None and str(goal).strip() else None


def replace_master_email_variants(
    db: Session,
    run_id: int,
    variants: list[dict[str, str]],
) -> None:
    db.query(RunMasterEmailVariant).filter(RunMasterEmailVariant.run_id == run_id).delete(
        synchronize_session=False
    )
    for i, v in enumerate(variants):
        subj = (v.get("subject") or "").strip()
        body = (v.get("body") or "").strip()
        db.add(
            RunMasterEmailVariant(
                run_id=run_id,
                position=i,
                subject=subj,
                body=body,
            )
        )


def effective_input_json_for_api(db: Session, run: Run) -> dict[str, Any]:
    """Relational input only: ``input_goal`` + entity_json_kv — never merge legacy ``runs.input_json``."""
    d: dict[str, Any] = {}
    if run.input_goal:
        d["goal"] = run.input_goal
    d.update(get_kv_dict(db, SCOPE_RUN_INPUT, run.id))
    return d


def effective_context_json_for_api(db: Session, run: Run) -> dict[str, Any]:
    """
    API-shaped ``context`` dict from ``run_outreach_context`` + KV extras only.
    Does not read legacy ``runs.context_json`` blobs.
    """
    oc = getattr(run, "outreach_context", None)
    if oc is not None:
        inner = {
            "offer": coalesce_str(oc.offer),
            "target_entities": coalesce_str(oc.target_entities),
            "target_roles": coalesce_str(oc.target_roles),
            "goal": coalesce_str(oc.goal),
            "tone": coalesce_str(oc.tone) or "Professional",
            "notes": coalesce_str(oc.notes),
        }
        outer: dict[str, Any] = {"context": wrap_context(inner)["context"]}
    else:
        inner = {
            "offer": "",
            "target_entities": "",
            "target_roles": "",
            "goal": coalesce_str(getattr(run, "input_goal", None)),
            "tone": "Professional",
            "notes": "",
        }
        outer = {"context": wrap_context(inner)["context"]}

    extras = get_kv_dict(db, SCOPE_RUN_CONTEXT_EXTRA, run.id)
    if extras:
        merged = dict(outer)
        merged.update(extras)
        return merged
    return outer


def effective_master_email_for_api(db: Session, run: Run) -> dict[str, Any] | None:
    """``run_master_email_variants`` only — never legacy ``runs.master_email`` JSON."""
    vs = list(getattr(run, "master_email_variants", None) or [])
    if vs:
        vs_sorted = sorted(vs, key=lambda x: x.position)
        return {"variants": [{"subject": x.subject, "body": x.body} for x in vs_sorted]}
    return None
