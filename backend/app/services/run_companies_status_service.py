"""Companies collected for a run + derived contact-discovery status per company."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Literal, TypedDict

from sqlalchemy.orm import Session

from app.repositories.run_company_repo import list_run_companies_sparse
from app.repositories.step_repo import (
    get_find_contacts_for_matching,
    get_step_id_by_run_and_name,
    get_step_status_by_run_and_name,
)

_log = logging.getLogger(__name__)


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


class CompanyStatusRow(TypedDict):
    collect_index: int
    name: str
    website: str
    contact_status: Literal["found", "none", "pending", "no_email", "llm_error"]


def _one_company_row(
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
        return {
            "collect_index": i,
            "name": name,
            "website": website,
            "contact_status": "llm_error",
        }
    ckeys = _entity_keys(co)
    matching = _matching_contacts(ckeys, raw_contacts, key_index)
    has_match = bool(matching)
    has_email = any(_contact_has_usable_email(ct) for ct in matching)
    if has_email:
        status: Literal["found", "none", "pending", "no_email"] = "found"
    elif has_match and find_completed:
        status = "no_email"
    elif find_completed:
        status = "none"
    else:
        status = "pending"
    return {
        "collect_index": i,
        "name": name,
        "website": website,
        "contact_status": status,
    }


def get_run_companies_with_status(
    db: Session,
    run_id: int,
    *,
    limit: int | None = None,
    offset: int = 0,
    q: str | None = None,
) -> dict:
    """
    contact_status:
    - llm_error: collect row marked llm_hallucination (invalid/unreachable website) — no contact search
    - found: at least one matching contact has a usable email
    - no_email: find completed; matching contacts exist but none have an email (UI: «Not available»)
    - none: find_contacts step completed and no matching contact
    - pending: find not finished yet (or not started), so we may still search
    """
    t_all0 = time.perf_counter()
    t_db0 = time.perf_counter()
    collect_step_id = get_step_id_by_run_and_name(db, run_id, "collect_companies")
    find_step_id = get_step_id_by_run_and_name(db, run_id, "find_contacts")
    collect_status = get_step_status_by_run_and_name(db, run_id, "collect_companies")
    find_status = get_step_status_by_run_and_name(db, run_id, "find_contacts")
    raw_contacts, contacts_load_tag = get_find_contacts_for_matching(db, run_id)
    db_steps_ms = (time.perf_counter() - t_db0) * 1000

    raw_companies = list_run_companies_sparse(db, run_id)
    if not isinstance(raw_companies, list):
        raw_companies = []

    find_completed = find_status == "completed"

    t_build0 = time.perf_counter()
    key_index = _contact_key_index(raw_contacts)
    rows: list[CompanyStatusRow] = []
    page: list[CompanyStatusRow] = []

    if q and q.strip():
        nq = q.strip().lower()
        for i, co in enumerate(raw_companies):
            if not isinstance(co, dict):
                continue
            rows.append(_one_company_row(i, co, raw_contacts=raw_contacts, key_index=key_index, find_completed=find_completed))
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
        dict_indices = [i for i, co in enumerate(raw_companies) if isinstance(co, dict)]
        total = len(dict_indices)
        start = max(0, offset)
        if limit is None:
            for pos in range(start, total):
                i = dict_indices[pos]
                co = raw_companies[i]
                assert isinstance(co, dict)
                rows.append(
                    _one_company_row(
                        i,
                        co,
                        raw_contacts=raw_contacts,
                        key_index=key_index,
                        find_completed=find_completed,
                    ),
                )
            page = rows
        else:
            lim = max(1, limit)
            for pos in range(start, min(start + lim, total)):
                i = dict_indices[pos]
                co = raw_companies[i]
                assert isinstance(co, dict)
                page.append(
                    _one_company_row(
                        i,
                        co,
                        raw_contacts=raw_contacts,
                        key_index=key_index,
                        find_completed=find_completed,
                    ),
                )

    build_rows_ms = (time.perf_counter() - t_build0) * 1000

    t_filter0 = time.perf_counter()
    filter_and_page_ms = (time.perf_counter() - t_filter0) * 1000
    total_ms = (time.perf_counter() - t_all0) * 1000

    _log.info(
        "run_companies rid=%s limit=%s offset=%s q=%r "
        "db_steps_ms=%.2f contacts_load=%s collect_step_id=%s find_step_id=%s collect_status=%s find_status=%s "
        "raw_companies_len=%s raw_contacts_len=%s built_rows_count=%s page_len=%s "
        "build_rows_ms=%.2f filter_page_ms=%.2f "
        "companies_total=%s total_ms=%.2f",
        run_id,
        limit,
        offset,
        q,
        db_steps_ms,
        contacts_load_tag,
        collect_step_id,
        find_step_id,
        collect_status,
        find_status,
        len(raw_companies) if isinstance(raw_companies, list) else 0,
        len(raw_contacts) if isinstance(raw_contacts, list) else 0,
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
