"""Canonical store is ``run_companies``. If that table is empty, we fall back to legacy
``collect_companies`` step ``output_json["companies"]`` (same as migrate_run_companies_from_legacy_step_json)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RUN_COMPANY_EXTRA
from app.models.run_company import RunCompany
from app.utils.entity_kv_storage import delete_scope, get_kv_maps_for_entities
from app.utils.run_company_extra import effective_run_company_extra, persist_run_company_extra


def run_company_orm_to_dict(db: Session, r: RunCompany) -> dict[str, Any]:
    kv_one = get_kv_maps_for_entities(db, SCOPE_RUN_COMPANY_EXTRA, [r.id])
    return _row_to_dict(db, r, kv_by_id=kv_one)


def _legacy_company_dict_to_row_shape(co: dict) -> dict[str, Any]:
    """Same shape as ``_row_to_dict`` for dict rows still only in step JSON."""
    d: dict[str, Any] = {
        "name": str(co.get("name") or "").strip(),
        "website": str(co.get("website") or "").strip(),
    }
    raw_llm = co.get("llm_hallucination")
    if raw_llm is not None:
        d["llm_hallucination"] = bool(raw_llm)
    for k, v in co.items():
        if k in ("name", "website", "llm_hallucination"):
            continue
        if k not in d:
            d[k] = v
    return d


def _sparse_from_legacy_collect_step_json(db: Session, run_id: int) -> list:
    from app.repositories.step_repo import get_step_by_run_and_name

    step = get_step_by_run_and_name(db, run_id, "collect_companies")
    if not step:
        return []
    from app.utils.step_payload import effective_step_output_json

    out = effective_step_output_json(db, step)
    companies = out.get("companies")
    if not isinstance(companies, list) or not companies:
        return []
    sparse: list = [None] * len(companies)
    for i, co in enumerate(companies):
        if isinstance(co, dict):
            sparse[i] = _legacy_company_dict_to_row_shape(co)
    return sparse


def _row_to_dict(
    db: Session,
    r: RunCompany,
    kv_by_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": str(r.name or "").strip(),
        "website": str(r.website or "").strip(),
    }
    if r.llm_hallucination is not None:
        d["llm_hallucination"] = r.llm_hallucination
    if kv_by_id is not None:
        extra = dict(kv_by_id.get(r.id) or {})
        if not extra and dict(r.extra_json or {}):
            extra = effective_run_company_extra(db, r)
    else:
        extra = effective_run_company_extra(db, r)
    for k, v in extra.items():
        if k not in d:
            d[k] = v
    return d


def list_run_companies_sparse(db: Session, run_id: int) -> list:
    """List aligned by collect_index (may contain None holes). Uses DB table; if empty, legacy step JSON."""
    rows = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id)
        .order_by(RunCompany.collect_index.asc(), RunCompany.id.asc())
        .all()
    )
    if not rows:
        return _sparse_from_legacy_collect_step_json(db, run_id)
    ids = [r.id for r in rows]
    kv_by_id = get_kv_maps_for_entities(db, SCOPE_RUN_COMPANY_EXTRA, ids)
    max_i = max(r.collect_index for r in rows)
    out: list = [None] * (max_i + 1)
    for r in rows:
        out[r.collect_index] = _row_to_dict(db, r, kv_by_id=kv_by_id)
    return out


def get_company_dict_at_index(db: Session, run_id: int, collect_index: int) -> dict[str, Any] | None:
    r = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    if r:
        kv_one = get_kv_maps_for_entities(db, SCOPE_RUN_COMPANY_EXTRA, [r.id])
        return _row_to_dict(db, r, kv_by_id=kv_one)
    sparse = list_run_companies_sparse(db, run_id)
    if collect_index < 0 or collect_index >= len(sparse):
        return None
    x = sparse[collect_index]
    return x if isinstance(x, dict) else None


def count_run_companies(db: Session, run_id: int) -> int:
    n = db.query(RunCompany).filter(RunCompany.run_id == run_id).count()
    if n > 0:
        return n
    return sum(1 for x in _sparse_from_legacy_collect_step_json(db, run_id) if isinstance(x, dict))


def sync_run_companies_from_dicts(
    db: Session,
    run_id: int,
    companies: list,
    *,
    commit: bool = True,
) -> None:
    """Replace all rows for run_id; enumerate index is collect_index (non-dict slots are skipped)."""
    for old in db.query(RunCompany).filter(RunCompany.run_id == run_id).all():
        delete_scope(db, SCOPE_RUN_COMPANY_EXTRA, old.id)
    db.query(RunCompany).filter(RunCompany.run_id == run_id).delete(synchronize_session=False)
    for i, co in enumerate(companies):
        if not isinstance(co, dict):
            continue
        name = str(co.get("name") or "").strip()
        website = str(co.get("website") or "").strip()
        raw_llm = co.get("llm_hallucination")
        llm_val: bool | None
        if raw_llm is None:
            llm_val = None
        else:
            llm_val = bool(raw_llm)
        extra = {k: v for k, v in co.items() if k not in ("name", "website", "llm_hallucination")}
        rc = RunCompany(
            run_id=run_id,
            collect_index=i,
            name=name or None,
            website=website or None,
            llm_hallucination=llm_val,
            extra_json={},
        )
        db.add(rc)
        db.flush()
        persist_run_company_extra(db, rc, extra or {})
    if commit:
        db.commit()
    else:
        db.flush()
