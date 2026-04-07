"""Canonical store is ``run_companies``. If that table is empty, we fall back to legacy
``collect_companies`` step ``output_json["companies"]`` (same as migrate_run_companies_from_legacy_step_json)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RUN_COMPANY_EXTRA
from app.constants.run_company_contact_status import PERSISTED_CONTACT_STATUSES
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
    cs_col = getattr(r, "contact_status", None)
    if isinstance(cs_col, str) and cs_col in PERSISTED_CONTACT_STATUSES:
        d["contact_status"] = cs_col
    afs = getattr(r, "ai_fit_status", None)
    if isinstance(afs, str) and afs.strip():
        d["ai_fit_status"] = afs.strip()
    afr = getattr(r, "ai_fit_reason", None)
    if isinstance(afr, str) and afr.strip():
        d["ai_fit_reason"] = afr.strip()
    afc = getattr(r, "ai_fit_checked_at", None)
    if afc is not None:
        d["ai_fit_checked_at"] = afc.isoformat() + "Z"
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


def run_company_table_dict_from_row(r: RunCompany) -> dict[str, Any]:
    """Row shape for Human UI companies table (relational column + ``extra_json``; no entity_kv)."""
    d: dict[str, Any] = {
        "name": str(r.name or "").strip(),
        "website": str(r.website or "").strip(),
    }
    if r.llm_hallucination is not None:
        d["llm_hallucination"] = bool(r.llm_hallucination)
    extra = dict(r.extra_json or {})
    cs_col = getattr(r, "contact_status", None)
    if isinstance(cs_col, str) and cs_col in PERSISTED_CONTACT_STATUSES:
        d["contact_status"] = cs_col
    else:
        cs = extra.get("contact_status")
        if isinstance(cs, str) and cs in PERSISTED_CONTACT_STATUSES:
            d["contact_status"] = cs
    afs = getattr(r, "ai_fit_status", None)
    if isinstance(afs, str) and afs.strip():
        d["ai_fit_status"] = afs.strip()
    afr = getattr(r, "ai_fit_reason", None)
    if isinstance(afr, str) and afr.strip():
        d["ai_fit_reason"] = afr.strip()
    afc = getattr(r, "ai_fit_checked_at", None)
    if afc is not None:
        d["ai_fit_checked_at"] = afc.isoformat() + "Z"
    for k, v in extra.items():
        if k == "contact_status":
            continue
        if k not in d:
            d[k] = v
    return d


def run_company_has_table_rows(db: Session, run_id: int) -> bool:
    """True if ``run_companies`` has at least one row for this run (legacy step JSON otherwise)."""
    return (
        db.query(RunCompany.id)
        .filter(RunCompany.run_id == run_id)
        .limit(1)
        .first()
        is not None
    )


def iter_run_company_table_rows(
    db: Session,
    run_id: int,
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(collect_index, row_dict)`` in collect_index order — no O(max_index) sparse list allocation."""
    rows = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id)
        .order_by(RunCompany.collect_index.asc(), RunCompany.id.asc())
        .all()
    )
    if not rows:
        sparse = _sparse_from_legacy_collect_step_json(db, run_id)
        if not isinstance(sparse, list):
            return
        for i, co in enumerate(sparse):
            if isinstance(co, dict):
                yield i, co
        return
    for r in rows:
        yield r.collect_index, run_company_table_dict_from_row(r)


def fetch_run_companies_page_for_ui(
    db: Session,
    run_id: int,
    *,
    limit: int | None,
    offset: int,
    q: str | None,
) -> tuple[list[RunCompany], int]:
    """SQL-level limit/offset + optional name/website filter — avoids loading the full run into memory.

    Call only when :func:`run_company_has_table_rows` is true.
    """
    base = db.query(RunCompany).filter(RunCompany.run_id == run_id)
    if q and q.strip():
        pat = f"%{q.strip()}%"
        base = base.filter(or_(RunCompany.name.ilike(pat), RunCompany.website.ilike(pat)))
    total = int(base.count() or 0)
    ordered = base.order_by(RunCompany.collect_index.asc(), RunCompany.id.asc())
    start = max(0, int(offset))
    if start:
        ordered = ordered.offset(start)
    if limit is not None:
        ordered = ordered.limit(max(1, int(limit)))
    rows = ordered.all()
    return rows, total


def list_run_companies_sparse_table(db: Session, run_id: int) -> list:
    """
    Same shape as list_run_companies_sparse but **does not** query entity_kv (SCOPE_RUN_COMPANY_EXTRA).

    Used for GET /runs/:id/companies so the Human UI table stays fast; workers that need KV extras
    keep using list_run_companies_sparse.

    Prefer :func:`iter_run_company_table_rows` for status/recompute paths — it avoids allocating
    ``[None] * (max(collect_index)+1)`` when indexes are sparse or corrupt (can be gigabytes).
    """
    pairs = sorted(iter_run_company_table_rows(db, run_id), key=lambda x: x[0])
    if not pairs:
        return []
    max_i = pairs[-1][0]
    span = max_i + 1
    n = len(pairs)
    if span > 1_000_000:
        raise ValueError(f"run_id={run_id} collect_index too large (max={max_i})")
    if span > max(n * 4 + 1000, 500_000):
        raise ValueError(
            f"run_id={run_id} collect_index span {span} too large for sparse layout (n={n})",
        )
    out: list = [None] * span
    for i, co in pairs:
        out[i] = co
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
    old_rows = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id)
        .order_by(RunCompany.collect_index.asc(), RunCompany.id.asc())
        .all()
    )
    ids = [r.id for r in old_rows]
    kv_by_id = get_kv_maps_for_entities(db, SCOPE_RUN_COMPANY_EXTRA, ids) if ids else {}
    status_by_index: dict[int, str] = {}
    ai_fit_by_index: dict[int, tuple[str | None, str | None, Any]] = {}
    for r in old_rows:
        cs = getattr(r, "contact_status", None)
        if isinstance(cs, str) and cs in PERSISTED_CONTACT_STATUSES:
            status_by_index[r.collect_index] = cs
            continue
        ej = dict(r.extra_json or {})
        v = ej.get("contact_status")
        if isinstance(v, str) and v in PERSISTED_CONTACT_STATUSES:
            status_by_index[r.collect_index] = v
            continue
        kv = kv_by_id.get(r.id) or {}
        v2 = kv.get("contact_status")
        if isinstance(v2, str) and v2 in PERSISTED_CONTACT_STATUSES:
            status_by_index[r.collect_index] = v2
    for r in old_rows:
        chk = getattr(r, "ai_fit_checked_at", None)
        if chk is not None:
            ai_fit_by_index[r.collect_index] = (
                getattr(r, "ai_fit_status", None),
                getattr(r, "ai_fit_reason", None),
                chk,
            )
    for old in old_rows:
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
        incoming_cs = co.get("contact_status")
        if isinstance(incoming_cs, str) and incoming_cs in PERSISTED_CONTACT_STATUSES:
            preserved_cs: str | None = incoming_cs
        else:
            preserved_cs = status_by_index.get(i)
        extra = {
            k: v
            for k, v in co.items()
            if k not in ("name", "website", "llm_hallucination", "contact_status")
        }
        rc = RunCompany(
            run_id=run_id,
            collect_index=i,
            name=name or None,
            website=website or None,
            llm_hallucination=llm_val,
            contact_status=preserved_cs,
            extra_json={},
        )
        fit_tup = ai_fit_by_index.get(i)
        if fit_tup is not None:
            st, reason, checked = fit_tup
            rc.ai_fit_status = st
            rc.ai_fit_reason = reason
            rc.ai_fit_checked_at = checked
        db.add(rc)
        db.flush()
        persist_run_company_extra(db, rc, extra or {})
    if commit:
        db.commit()
    else:
        db.flush()
