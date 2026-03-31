"""Companies collected for a run + derived contact-discovery status per company."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from sqlalchemy.orm import Session

from app.repositories.step_repo import get_step_by_run_and_name


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
    if not company_keys:
        return False
    return bool(_entity_keys(contact) & company_keys)


class CompanyStatusRow(TypedDict):
    collect_index: int
    name: str
    website: str
    contact_status: Literal["found", "none", "pending"]


def get_run_companies_with_status(db: Session, run_id: int) -> dict:
    """
    contact_status:
    - found: at least one contact in find_contacts output matches this company
    - none: find_contacts step completed and no matching contact
    - pending: find not finished yet (or not started), so we may still search
    """
    step_collect = get_step_by_run_and_name(db, run_id, "collect_companies")
    step_find = get_step_by_run_and_name(db, run_id, "find_contacts")

    raw_companies = (step_collect.output_json or {}).get("companies") if step_collect else []
    if not isinstance(raw_companies, list):
        raw_companies = []

    raw_contacts = (step_find.output_json or {}).get("contacts") if step_find else []
    if not isinstance(raw_contacts, list):
        raw_contacts = []

    find_completed = bool(step_find and step_find.status == "completed")

    rows: list[CompanyStatusRow] = []
    for i, co in enumerate(raw_companies):
        if not isinstance(co, dict):
            continue
        name = str(co.get("name") or "").strip() or f"Company {i + 1}"
        website = str(co.get("website") or "").strip()
        ckeys = _entity_keys(co)
        has_contact = any(
            isinstance(ct, dict) and _contact_matches_company(ct, ckeys) for ct in raw_contacts
        )
        if has_contact:
            status: Literal["found", "none", "pending"] = "found"
        elif find_completed:
            status = "none"
        else:
            status = "pending"
        rows.append(
            {
                "collect_index": i,
                "name": name,
                "website": website,
                "contact_status": status,
            },
        )

    return {
        "companies": rows,
        "collect_step_status": step_collect.status if step_collect else None,
        "find_step_status": step_find.status if step_find else None,
    }
