"""Persist Tracking / Human UI state in relational tables (not runs.context_json)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.email_draft import EmailDraft
from app.models.run_event_chain_collapse import RunEventChainCollapse


def get_event_chain_collapsed_map(db: Session, run_id: int) -> dict[str, bool]:
    rows = (
        db.query(RunEventChainCollapse)
        .filter(RunEventChainCollapse.run_id == run_id)
        .all()
    )
    return {str(r.email_draft_id): bool(r.collapsed) for r in rows}


def merge_event_chain_collapsed(
    db: Session,
    run_id: int,
    *,
    event_chain_collapsed: dict[str, bool] | None,
) -> None:
    if not event_chain_collapsed:
        return
    for k, v in event_chain_collapsed.items():
        sk = str(k).strip()
        if not sk or not sk.isdigit():
            continue
        draft_id = int(sk)
        ok = (
            db.query(EmailDraft.id)
            .filter(EmailDraft.id == draft_id, EmailDraft.run_id == run_id)
            .first()
        )
        if not ok:
            continue
        row = (
            db.query(RunEventChainCollapse)
            .filter(
                RunEventChainCollapse.run_id == run_id,
                RunEventChainCollapse.email_draft_id == draft_id,
            )
            .first()
        )
        if row:
            row.collapsed = bool(v)
        else:
            db.add(
                RunEventChainCollapse(
                    run_id=run_id,
                    email_draft_id=draft_id,
                    collapsed=bool(v),
                )
            )
    db.flush()


def delete_human_ui_from_context_json(ctx: dict) -> dict:
    """Remove legacy _human_ui.event_chain_collapsed from a copy of context_json."""
    out = dict(ctx or {})
    ui = dict(out.get("_human_ui") or {})
    ui.pop("event_chain_collapsed", None)
    if ui:
        out["_human_ui"] = ui
    else:
        out.pop("_human_ui", None)
    return out
