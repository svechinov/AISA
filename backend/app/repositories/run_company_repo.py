"""Collected companies live only in run_companies; never in step output_json."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.run_company import RunCompany


def run_company_orm_to_dict(r: RunCompany) -> dict[str, Any]:
    return _row_to_dict(r)


def _row_to_dict(r: RunCompany) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": str(r.name or "").strip(),
        "website": str(r.website or "").strip(),
    }
    if r.llm_hallucination is not None:
        d["llm_hallucination"] = r.llm_hallucination
    extra = r.extra_json if isinstance(r.extra_json, dict) else {}
    for k, v in extra.items():
        if k not in d:
            d[k] = v
    return d


def list_run_companies_sparse(db: Session, run_id: int) -> list:
    """List aligned by collect_index (may contain None holes); empty list if no rows."""
    rows = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id)
        .order_by(RunCompany.collect_index.asc(), RunCompany.id.asc())
        .all()
    )
    if not rows:
        return []
    max_i = max(r.collect_index for r in rows)
    out: list = [None] * (max_i + 1)
    for r in rows:
        out[r.collect_index] = _row_to_dict(r)
    return out


def get_company_dict_at_index(db: Session, run_id: int, collect_index: int) -> dict[str, Any] | None:
    r = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    return _row_to_dict(r) if r else None


def count_run_companies(db: Session, run_id: int) -> int:
    return db.query(RunCompany).filter(RunCompany.run_id == run_id).count()


def sync_run_companies_from_dicts(
    db: Session,
    run_id: int,
    companies: list,
    *,
    commit: bool = True,
) -> None:
    """Replace all rows for run_id; enumerate index is collect_index (non-dict slots are skipped)."""
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
        db.add(
            RunCompany(
                run_id=run_id,
                collect_index=i,
                name=name or None,
                website=website or None,
                llm_hallucination=llm_val,
                extra_json=extra or {},
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()
