"""
Apollo.io REST API — organization search, people search, bulk enrichment (emails).

Uses x-api-key header. See https://docs.apollo.io/reference/organization-search
and https://docs.apollo.io/reference/people-api-search .
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.company_website_check import normalize_company_website_url
from app.services.run_context_service import coalesce_str, get_effective_context

logger = logging.getLogger(__name__)

APOLLO_BASE = "https://api.apollo.io/api/v1"


def apollo_configured() -> bool:
    return bool((settings.APOLLO_API_KEY or "").strip())


def domain_from_website(website: str) -> str | None:
    url = normalize_company_website_url(website)
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def keyword_tags_from_context(ctx: dict[str, str]) -> list[str]:
    parts = []
    for k in ("target_entities", "target_roles", "goal", "offer", "notes"):
        parts.append(coalesce_str(ctx.get(k)))
    text = " ".join(parts)
    tokens = re.split(r"[\s,;|]+", text)
    seen: set[str] = set()
    tags: list[str] = []
    for t in tokens:
        t = re.sub(r"^[\-–—•]+|[\-–—•]+$", "", t.strip())
        if len(t) < 2 or len(t) > 48:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        tags.append(t)
        if len(tags) >= 5:
            break
    if not tags:
        tags = ["business"]
    return tags


def person_titles_from_context(ctx: dict[str, str]) -> list[str]:
    raw = coalesce_str(ctx.get("target_roles"))
    titles: list[str] = []
    if raw:
        for line in raw.replace(";", "\n").splitlines():
            for part in line.split(","):
                t = part.strip()
                if len(t) >= 2:
                    titles.append(t)
    if not titles:
        titles = [
            "ceo",
            "founder",
            "owner",
            "vice president",
            "director",
            "head",
            "manager",
            "marketing",
            "sales",
            "business development",
        ]
    return titles[:12]


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": (settings.APOLLO_API_KEY or "").strip(),
    }


def _apollo_post(path: str, *, params: list[tuple[str, Any]], json_body: dict | None = None) -> dict:
    url = f"{APOLLO_BASE}{path}"
    timeout = httpx.Timeout(settings.APOLLO_HTTP_TIMEOUT_SEC)
    body = json_body if json_body is not None else {}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, headers=_headers(), params=params, json=body)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, dict) else {}


def organization_row_to_company(org: dict[str, Any]) -> dict[str, Any] | None:
    name = (org.get("name") or "").strip()
    pd = (org.get("primary_domain") or "").strip().lower()
    if not name or not pd:
        return None
    wu = (org.get("website_url") or "").strip()
    if wu.startswith("http://") or wu.startswith("https://"):
        website = wu
    else:
        website = f"https://{pd}"
    return {"name": name, "website": website}


def search_organizations_json(keyword_tags: list[str], *, page: int, per_page: int) -> dict:
    params: list[tuple[str, Any]] = [("page", page), ("per_page", per_page)]
    for t in keyword_tags:
        params.append(("q_organization_keyword_tags[]", t))
    return _apollo_post("/mixed_companies/search", params=params, json_body={})


def search_people_json(domain: str, person_titles: list[str], *, per_page: int) -> dict:
    params: list[tuple[str, Any]] = [
        ("page", 1),
        ("per_page", per_page),
        ("q_organization_domains_list[]", domain),
    ]
    for t in person_titles:
        params.append(("person_titles[]", t))
    return _apollo_post("/mixed_people/api_search", params=params, json_body={})


def bulk_match_people(ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), 10):
        chunk = ids[i : i + 10]
        if not chunk:
            continue
        params: list[tuple[str, Any]] = [("reveal_personal_emails", "true")]
        body = {"details": [{"id": pid} for pid in chunk]}
        data = _apollo_post("/people/bulk_match", params=params, json_body=body)
        if (data.get("status") or "").lower() == "failed":
            logger.warning(
                "Apollo bulk_match failed: %s",
                data.get("error_message") or data.get("error_code") or data,
            )
            continue
        matches = data.get("matches")
        if isinstance(matches, list):
            out.extend([m for m in matches if isinstance(m, dict)])
    return out


def try_collect_companies_via_apollo(
    db,
    run_id: int,
    run,
    *,
    continuation: bool,
) -> dict[str, Any] | None:
    """
    Returns {"companies": [...]} with new orgs not already present by domain, or None to use LLM.
    """
    if not apollo_configured():
        return None
    ctx = get_effective_context(run)
    tags = keyword_tags_from_context(ctx)
    prior = list_run_companies_sparse(db, run_id)
    prior_domains: set[str] = set()
    for c in prior:
        if not isinstance(c, dict):
            continue
        d = domain_from_website(str(c.get("website") or ""))
        if d:
            prior_domains.add(d)

    per_page = min(
        settings.APOLLO_MAX_ORG_PAGE_SIZE,
        50 if continuation else 25,
    )
    try:
        data = search_organizations_json(tags, page=1, per_page=per_page)
    except Exception:
        logger.exception("Apollo organization search failed; falling back to LLM")
        return None

    orgs = data.get("organizations")
    if not isinstance(orgs, list):
        orgs = []
    rows: list[dict[str, Any]] = []
    for org in orgs:
        if not isinstance(org, dict):
            continue
        row = organization_row_to_company(org)
        if not row:
            continue
        dom = domain_from_website(row["website"])
        if dom and dom in prior_domains:
            continue
        rows.append(row)
        if dom:
            prior_domains.add(dom)

    if not rows:
        logger.info("Apollo organization search returned no new companies; falling back to LLM")
        return None
    return {"companies": rows}


def try_find_contacts_via_apollo(db, run_id: int, run, step_input: dict) -> dict[str, Any] | None:
    """
    Returns {"contacts": [...]} or None to use LLM (not configured, error, or no contacts found).
    """
    if not apollo_configured():
        return None

    companies = step_input.get("companies") if isinstance(step_input, dict) else None
    if not isinstance(companies, list):
        companies = []
    if not companies:
        companies = list_run_companies_sparse(db, run_id)

    grounded = [
        c
        for c in companies
        if isinstance(c, dict) and not c.get("llm_hallucination")
    ]
    if not grounded:
        logger.info("Apollo find_contacts: no grounded companies; falling back to LLM")
        return None

    ctx = get_effective_context(run)
    titles = person_titles_from_context(ctx)
    per_co = max(1, int(settings.APOLLO_MAX_PEOPLE_PER_COMPANY))
    cap = max(1, int(settings.APOLLO_MAX_PEOPLE_TOTAL))
    contacts: list[dict[str, Any]] = []
    remaining = cap

    try:
        for co in grounded:
            if remaining <= 0:
                break
            name = (co.get("name") or "").strip() or "—"
            website = (co.get("website") or "").strip()
            domain = domain_from_website(website)
            if not domain:
                continue

            pdata = search_people_json(domain, titles, per_page=min(per_co, 25, remaining))
            people = pdata.get("people")
            if not isinstance(people, list) or not people:
                continue

            ids: list[str] = []
            for p in people:
                if not isinstance(p, dict):
                    continue
                pid = (p.get("id") or "").strip()
                if pid:
                    ids.append(pid)
                if len(ids) >= min(per_co, remaining):
                    break
            if not ids:
                continue

            matches = bulk_match_people(ids[: min(len(ids), remaining)])
            for m in matches:
                email = (m.get("email") or "").strip()
                role = (m.get("title") or "").strip()
                full = (m.get("name") or "").strip()
                if not full:
                    fn = (m.get("first_name") or "").strip()
                    ln = (m.get("last_name") or "").strip()
                    full = f"{fn} {ln}".strip() or "—"
                contacts.append(
                    {
                        "company": name,
                        "website": website,
                        "name": full,
                        "role": role,
                        "email": email,
                    }
                )
                remaining -= 1
                if remaining <= 0:
                    break
    except Exception:
        logger.exception("Apollo find_contacts failed; falling back to LLM")
        return None

    if not contacts:
        logger.info("Apollo find_contacts returned no contacts; falling back to LLM")
        return None
    return {"contacts": contacts}
