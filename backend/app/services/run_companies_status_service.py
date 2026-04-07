"""Companies collected for a run + derived contact-discovery status per company."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Literal, TypedDict

from sqlalchemy.orm import Session

from app.models.run_company import RunCompany
from app.repositories.run_company_repo import (
    fetch_run_companies_page_for_ui,
    iter_run_company_table_rows,
    run_company_has_table_rows,
    run_company_table_dict_from_row,
)
from app.repositories.step_repo import (
    get_collect_and_find_steps_meta,
    get_find_contacts_for_matching,
    get_step_status_by_run_and_name,
)
from app.constants.run_company_contact_status import PERSISTED_CONTACT_STATUSES

_log = logging.getLogger(__name__)

# Cap rows read from ``contacts`` when recomputing status (workers / retry — not GET /companies).
_MAX_CONTACTS_FOR_STATUS_MATCH = 50_000


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _strip_url(url: str) -> str:
    u = _norm(url)
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.strip("/").rstrip("/")


def _entity_keys(row: dict) -> set[str]:
    """Keys for matching company rows and contact rows."""
    keys: set[str] = set()
    name = _norm(row.get("name") or "")
    if name:
        keys.add(name)
    web = row.get("website") or ""
    if web:
        keys.add(_strip_url(web))
        keys.add(_norm(web))
    return {k for k in keys if k}


def _contact_matches_company(contact: dict, company_keys: set[str]) -> bool:
    """Used by retry_company_find_service and elsewhere — keep exported for imports."""
    if not company_keys:
        return False
    return bool(_entity_keys(contact) & company_keys)


def _contact_has_usable_email(contact: dict) -> bool:
    em = str(contact.get("email") or "").strip()
    return bool(em and "@" in em)


def _contact_key_index(raw_contacts: list) -> dict[str, list[int]]:
    """Map entity key → contact indices (for O(keys) lookup instead of scanning all contacts per company)."""
    idx: dict[str, list[int]] = defaultdict(list)
    for j, ct in enumerate(raw_contacts):
        if not isinstance(ct, dict):
            continue
        for k in _entity_keys(ct):
            idx[k].append(j)
    return idx


def _matching_contacts(
    ckeys: set[str],
    raw_contacts: list,
    key_index: dict[str, list[int]],
) -> list[dict]:
    """Contacts whose entity keys intersect ckeys (same semantics as scanning all contacts per company)."""
    if not ckeys:
        return []
    seen: set[int] = set()
    for k in ckeys:
        for j in key_index.get(k, ()):
            if j in seen:
                continue
            ct = raw_contacts[j]
            if isinstance(ct, dict):
                seen.add(j)
    return [raw_contacts[j] for j in seen]


class CompanyStatusRow(TypedDict, total=False):
    collect_index: int
    name: str
    website: str
    contact_status: Literal[
        "found",
        "none",
        "pending",
        "no_email",
        "llm_error",
        "unknown",
    ]
    ai_fit_status: Literal["correct", "incorrect"]
    ai_fit_reason: str
    ai_fit_checked_at: str


def _merge_ai_fit_from_company_dict(co: dict, row: dict) -> dict:
    v = co.get("ai_fit_status")
    if isinstance(v, str) and v in ("correct", "incorrect"):
        row["ai_fit_status"] = v  # type: ignore[typeddict-item]
    r = co.get("ai_fit_reason")
    if isinstance(r, str) and r.strip():
        row["ai_fit_reason"] = r.strip()[:2000]
    t = co.get("ai_fit_checked_at")
    if isinstance(t, str) and t.strip():
        row["ai_fit_checked_at"] = t.strip()
    return row


def _one_company_row_with_contacts(
    i: int,
    co: dict,
    *,
    raw_contacts: list,
    key_index: dict[str, list[int]],
    find_completed: bool,
) -> CompanyStatusRow:
    name = str(co.get("name") or "").strip() or f"Company {i + 1}"
    website = str(co.get("website") or "").strip()
    if co.get("llm_hallucination") is True:
        return _merge_ai_fit_from_company_dict(
            co,
            {
                "collect_index": i,
                "name": name,
                "website": website,
                "contact_status": "llm_error",
            },
        )
    ckeys = _entity_keys(co)
    matching = _matching_contacts(ckeys, raw_contacts, key_index)
    has_match = bool(matching)
    has_email = any(_contact_has_usable_email(ct) for ct in matching)
    if has_email:
        status: Literal["found", "none", "pending", "no_email", "llm_error", "unknown"] = "found"
    elif has_match and find_completed:
        status = "no_email"
    elif find_completed:
        status = "none"
    else:
        status = "pending"
    out: dict = {
        "collect_index": i,
        "name": name,
        "website": website,
        "contact_status": status,
    }
    return _merge_ai_fit_from_company_dict(co, out)


def _one_company_row_lite(
    i: int,
    co: dict,
    *,
    find_completed: bool,
) -> CompanyStatusRow:
    """GET /companies: no contacts query — use persisted ``run_companies.contact_status`` when present."""
    name = str(co.get("name") or "").strip() or f"Company {i + 1}"
    website = str(co.get("website") or "").strip()
    if co.get("llm_hallucination") is True:
        return _merge_ai_fit_from_company_dict(
            co,
            {
                "collect_index": i,
                "name": name,
                "website": website,
                "contact_status": "llm_error",
            },
        )
    persisted = co.get("contact_status")
    if isinstance(persisted, str) and persisted in PERSISTED_CONTACT_STATUSES:
        return _merge_ai_fit_from_company_dict(
            co,
            {
                "collect_index": i,
                "name": name,
                "website": website,
                "contact_status": persisted,  # type: ignore[typeddict-item]
            },
        )
    if not find_completed:
        return _merge_ai_fit_from_company_dict(
            co,
            {
                "collect_index": i,
                "name": name,
                "website": website,
                "contact_status": "pending",
            },
        )
    return _merge_ai_fit_from_company_dict(
        co,
        {
            "collect_index": i,
            "name": name,
            "website": website,
            "contact_status": "unknown",
        },
    )


def _persist_run_company_contact_status(
    db: Session,
    run_id: int,
    collect_index: int,
    status: str,
) -> None:
    if status not in PERSISTED_CONTACT_STATUSES:
        return
    r = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    if not r:
        return
    r.contact_status = status
    db.add(r)


def recompute_and_persist_contact_statuses_for_run(db: Session, run_id: int) -> None:
    """
    Loads contacts once, computes per-row status, persists into ``run_companies.contact_status``.

    Call after find/retry/continue paths have written the ``contacts`` table — never from GET /companies.
    """
    find_status = get_step_status_by_run_and_name(db, run_id, "find_contacts")
    find_completed = find_status == "completed"
    raw_contacts, _tag = get_find_contacts_for_matching(
        db,
        run_id,
        limit=_MAX_CONTACTS_FOR_STATUS_MATCH,
    )
    key_index = _contact_key_index(raw_contacts)
    for collect_index, co in iter_run_company_table_rows(db, run_id):
        co_clean = {k: v for k, v in co.items() if k != "contact_status"}
        row = _one_company_row_with_contacts(
            collect_index,
            co_clean,
            raw_contacts=raw_contacts,
            key_index=key_index,
            find_completed=find_completed,
        )
        _persist_run_company_contact_status(db, run_id, collect_index, row["contact_status"])
    db.commit()


def get_run_companies_with_status(
    db: Session,
    run_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
    q: str | None = None,
) -> dict:
    """
    Human UI companies table.

    Does **not** query the ``contacts`` table. Row-level ``contact_status`` comes from the
    ``run_companies.contact_status`` column when set by ``recompute_and_persist_contact_statuses_for_run``
    (after find/retry). Otherwise: ``llm_error``, ``pending`` (find not completed), or ``unknown`` (find
    completed but status not synced yet).
    """
    t_all0 = time.perf_counter()
    t_db0 = time.perf_counter()
    meta = get_collect_and_find_steps_meta(db, run_id)
    collect_step_id = meta.get("collect_step_id")
    find_step_id = meta.get("find_step_id")
    collect_status = meta.get("collect_status")
    find_status = meta.get("find_status")
    db_steps_ms = (time.perf_counter() - t_db0) * 1000

    find_completed = find_status == "completed"
    start = max(0, offset)

    # Table-backed runs: LIMIT/OFFSET in SQL — do not load every company row then slice in Python.
    if run_company_has_table_rows(db, run_id):
        t_build0 = time.perf_counter()
        rows_orm, total = fetch_run_companies_page_for_ui(
            db, run_id, limit=limit, offset=offset, q=q
        )
        page = [
            _one_company_row_lite(
                r.collect_index,
                run_company_table_dict_from_row(r),
                find_completed=find_completed,
            )
            for r in rows_orm
        ]
        build_rows_ms = (time.perf_counter() - t_build0) * 1000
        filter_and_page_ms = 0.0
        total_ms = (time.perf_counter() - t_all0) * 1000
        _log_method = _log.info if total_ms >= 500.0 else _log.debug
        _log_method(
            "run_companies rid=%s limit=%s offset=%s q=%r fast_path=table "
            "db_steps_ms=%.2f contacts_load=none collect_step_id=%s find_step_id=%s collect_status=%s find_status=%s "
            "table_total=%s page_len=%s build_rows_ms=%.2f filter_page_ms=%.2f total_ms=%.2f",
            run_id,
            limit,
            offset,
            q,
            db_steps_ms,
            collect_step_id,
            find_step_id,
            collect_status,
            find_status,
            total,
            len(page),
            build_rows_ms,
            filter_and_page_ms,
            total_ms,
        )
        return {
            "companies": page,
            "companies_total": total,
            "limit": limit,
            "offset": start,
            "collect_step_status": collect_status,
            "find_step_status": find_status,
        }

    pairs = list(iter_run_company_table_rows(db, run_id))

    t_build0 = time.perf_counter()
    rows: list[CompanyStatusRow] = []
    page: list[CompanyStatusRow] = []

    if q and q.strip():
        nq = q.strip().lower()
        for collect_index, co in pairs:
            rows.append(_one_company_row_lite(collect_index, co, find_completed=find_completed))
        filtered = [
            r
            for r in rows
            if nq in (r["name"] or "").lower() or nq in (r["website"] or "").lower()
        ]
        total = len(filtered)
        start = max(0, offset)
        if limit is not None:
            page = filtered[start : start + max(1, limit)]
        else:
            page = filtered[start:]
    else:
        total = len(pairs)
        start = max(0, offset)
        if limit is None:
            for pos in range(start, total):
                collect_index, co = pairs[pos]
                rows.append(
                    _one_company_row_lite(
                        collect_index,
                        co,
                        find_completed=find_completed,
                    ),
                )
            page = rows
        else:
            lim = max(1, limit)
            for pos in range(start, min(start + lim, total)):
                collect_index, co = pairs[pos]
                page.append(
                    _one_company_row_lite(
                        collect_index,
                        co,
                        find_completed=find_completed,
                    ),
                )

    build_rows_ms = (time.perf_counter() - t_build0) * 1000

    t_filter0 = time.perf_counter()
    filter_and_page_ms = (time.perf_counter() - t_filter0) * 1000
    total_ms = (time.perf_counter() - t_all0) * 1000

    _log_method = _log.info if total_ms >= 500.0 else _log.debug
    _log_method(
        "run_companies rid=%s limit=%s offset=%s q=%r "
        "db_steps_ms=%.2f contacts_load=none collect_step_id=%s find_step_id=%s collect_status=%s find_status=%s "
        "raw_companies_len=%s raw_contacts_len=0 built_rows_count=%s page_len=%s "
        "build_rows_ms=%.2f filter_page_ms=%.2f "
        "companies_total=%s total_ms=%.2f",
        run_id,
        limit,
        offset,
        q,
        db_steps_ms,
        collect_step_id,
        find_step_id,
        collect_status,
        find_status,
        len(pairs),
        len(rows) if q and q.strip() else len(page),
        len(page),
        build_rows_ms,
        filter_and_page_ms,
        total,
        total_ms,
    )

    return {
        "companies": page,
        "companies_total": total,
        "limit": limit,
        "offset": start,
        "collect_step_status": collect_status,
        "find_step_status": find_status,
    }
