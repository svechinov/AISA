"""CRUD for entity_json_kv (replaces free-form JSON blobs per entity)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models.entity_json_kv import EntityJsonKV


def delete_scope(db: Session, scope: str, entity_id: int) -> int:
    q = db.query(EntityJsonKV).filter(EntityJsonKV.scope == scope, EntityJsonKV.entity_id == entity_id)
    n = q.count()
    q.delete(synchronize_session=False)
    return n


def get_kv_maps_for_entities(
    db: Session,
    scope: str,
    entity_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """One query: entity_id → merged key/value dict (same shape as get_kv_dict per entity)."""
    if not entity_ids:
        return {}
    rows = (
        db.query(EntityJsonKV)
        .filter(EntityJsonKV.scope == scope, EntityJsonKV.entity_id.in_(entity_ids))
        .order_by(EntityJsonKV.entity_id.asc(), EntityJsonKV.id.asc())
        .all()
    )
    merged: dict[int, dict[str, Any]] = defaultdict(dict)
    for r in rows:
        merged[r.entity_id][r.key] = r.value_json
    return {eid: dict(d) for eid, d in merged.items()}


def get_kv_dict(db: Session, scope: str, entity_id: int) -> dict[str, Any]:
    rows = (
        db.query(EntityJsonKV)
        .filter(EntityJsonKV.scope == scope, EntityJsonKV.entity_id == entity_id)
        .order_by(EntityJsonKV.id.asc())
        .all()
    )
    return {r.key: r.value_json for r in rows}


def replace_kv_dict(db: Session, scope: str, entity_id: int, data: dict[str, Any] | None) -> None:
    delete_scope(db, scope, entity_id)
    if not data:
        return
    for k, v in data.items():
        if not isinstance(k, str) or not k:
            continue
        db.add(EntityJsonKV(scope=scope, entity_id=entity_id, key=k[:255], value_json=v))


def absorb_legacy_kv_into_scope(
    db: Session,
    scope: str,
    entity_id: int,
    legacy: dict[str, Any] | None,
    *,
    clear_legacy: Callable[[], None],
) -> dict[str, Any]:
    """Return KV dict. If KV is empty and ``legacy`` is non-empty, copy into KV, clear legacy column, return data."""
    d = get_kv_dict(db, scope, entity_id)
    if d:
        return d
    leg = dict(legacy or {})
    if not leg:
        return {}
    replace_kv_dict(db, scope, entity_id, leg)
    clear_legacy()
    return leg


def merge_kv_dict(db: Session, scope: str, entity_id: int, patch: dict[str, Any] | None) -> None:
    if not patch:
        return
    for k, v in patch.items():
        if not isinstance(k, str) or not k:
            continue
        row = (
            db.query(EntityJsonKV)
            .filter(EntityJsonKV.scope == scope, EntityJsonKV.entity_id == entity_id, EntityJsonKV.key == k[:255])
            .first()
        )
        if row is None:
            db.add(EntityJsonKV(scope=scope, entity_id=entity_id, key=k[:255], value_json=v))
        else:
            row.value_json = v
