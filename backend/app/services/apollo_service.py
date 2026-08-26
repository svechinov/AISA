"""
Apollo.io REST API — organization search, people search, bulk enrichment (emails).

Uses ``x-api-key`` header. Company discovery: ``POST /organizations/search`` (JSON body).
People discovery: ``POST /mixed_people/api_search`` (JSON body). Employee-size filter applies only to
company search — not people search (avoids empty results when Apollo headcount ≠ collected org).
See https://docs.apollo.io/reference/people-api-search .
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.apollo_llm_hints import apollo_llm_hints_for_run
from app.services.human_ui_activity import push_human_ui_activity, push_human_ui_activity_once
from app.services.company_website_check import normalize_company_website_url
from app.services.contact_name_check import annotate_surname_check
from app.services.run_context_service import coalesce_str, get_effective_context

logger = logging.getLogger(__name__)

APOLLO_BASE = "https://api.apollo.io/api/v1"

# Employee-count buckets for «up to 100 people at the company» (Apollo UI: 1–10, 11–20, 21–50, 51–100).
_APOLLO_ORG_NUM_EMPLOYEES_RANGES_UP_TO_100: tuple[str, str, str, str] = (
    "1,10",
    "11,20",
    "21,50",
    "51,100",
)


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


# B-274: second-pass titles for companies where the run's own narrow title list found nobody. The
# 29.07 add-on wave (Bonfire, Gardens) returned 0-1 people for the run titles, while a direct Apollo
# query with these hiring-side titles surfaced live people with verified addresses — the data was
# there, we were asking for the wrong roles (confirms B-241). Kept small and generic on purpose: it
# is a fallback, not a widening of the campaign's targeting.
FALLBACK_PERSON_TITLES: tuple[str, ...] = (
    "head of people",
    "head of talent",
    "head of hr",
    "talent acquisition",
    "recruiting",
    "recruiter",
    "people operations",
    "hr manager",
    "hr director",
    "chief of staff",
    "studio head",
    "co-founder",
)


def fallback_person_titles(primary_titles: list[str]) -> list[str]:
    """Second-pass titles: the standing hiring-side list minus whatever the first pass already
    tried (no point re-asking Apollo the same question)."""
    tried = {str(t).strip().lower() for t in primary_titles if str(t or "").strip()}
    return [t for t in FALLBACK_PERSON_TITLES if t not in tried]


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


def _apollo_post_json(path: str, *, json_body: dict[str, Any]) -> dict:
    """POST with JSON body only (no query string) — matches Apollo ``/organizations/search`` usage."""
    url = f"{APOLLO_BASE}{path}"
    timeout = httpx.Timeout(settings.APOLLO_HTTP_TIMEOUT_SEC)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, headers=_headers(), json=json_body)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, dict) else {}


def organization_row_to_company(org: dict[str, Any]) -> dict[str, Any] | None:
    name = (org.get("name") or "").strip()
    pd = (org.get("primary_domain") or org.get("domain") or "").strip().lower()
    if not name or not pd:
        return None
    wu = (org.get("website_url") or "").strip()
    if wu.startswith("http://") or wu.startswith("https://"):
        website = wu
    else:
        website = f"https://{pd}"
    return {"name": name, "website": website}


def _organizations_from_apollo_search_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize org list from Apollo search responses (field name varies by endpoint)."""
    for key in ("organizations", "accounts", "mixed_companies", "companies"):
        v = data.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    return []


def apollo_org_filters_from_run_setup(run_setup: Any) -> dict[str, list[str]]:
    """Derive Apollo org-search filters from RunSetup.icp_criteria_json / icp_min_employees / icp_max_employees.

    Total: never raises, regardless of how malformed run_setup / icp_criteria_json is.
    - locations: run_setup.icp_criteria_json["regions"] — stripped, deduped, capped at 20; [] if unset/malformed
      (no location filter applied).
    - num_employees_ranges: one "{lo},{hi}" range from icp_min_employees / icp_max_employees; falls back to the
      legacy ≤100 buckets when neither bound is set (keeps existing behavior for runs without a band — no silent
      widening of the search).
    """
    locations: list[str] = []
    crit = getattr(run_setup, "icp_criteria_json", None)
    if isinstance(crit, dict):
        regions = crit.get("regions")
        if isinstance(regions, list):
            seen: set[str] = set()
            for r in regions:
                if not isinstance(r, str):
                    continue
                r = r.strip()
                if not r or r in seen:
                    continue
                seen.add(r)
                locations.append(r)
                if len(locations) >= 20:
                    break

    def _bound(v: Any) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else None

    lo = _bound(getattr(run_setup, "icp_min_employees", None))
    hi = _bound(getattr(run_setup, "icp_max_employees", None))
    if lo is not None and hi is not None:
        if lo > hi:
            lo, hi = hi, lo
        num_employees_ranges = [f"{lo},{hi}"]
    elif lo is not None:
        num_employees_ranges = [f"{lo},100000"]
    elif hi is not None:
        num_employees_ranges = [f"1,{hi}"]
    else:
        num_employees_ranges = list(_APOLLO_ORG_NUM_EMPLOYEES_RANGES_UP_TO_100)

    return {"locations": locations, "num_employees_ranges": num_employees_ranges}


def search_organizations_json(
    keyword_tags: list[str],
    *,
    page: int,
    per_page: int,
    locations: list[str] | None = None,
    num_employees_ranges: list[str] | None = None,
) -> dict:
    """Company search via ``POST /organizations/search`` (JSON body)."""
    tags = [str(t).strip() for t in keyword_tags if t and str(t).strip()]
    per = min(max(1, int(per_page)), 100)
    pg = max(1, int(page))
    body: dict[str, Any] = {
        "page": pg,
        "per_page": per,
        "organization_num_employees_ranges": (
            list(num_employees_ranges) if num_employees_ranges else list(_APOLLO_ORG_NUM_EMPLOYEES_RANGES_UP_TO_100)
        ),
    }
    if locations:
        body["organization_locations"] = list(locations)
    if tags:
        body["q_organization_keyword_tags"] = tags[:20]
    else:
        body["q_keywords"] = "business"
    return _apollo_post_json("/organizations/search", json_body=body)


def search_people_json(domain: str, person_titles: list[str], *, per_page: int) -> dict:
    """People search: same JSON shape as Apollo docs; no duplicate employee filter (companies already ≤100)."""
    dom = (domain or "").strip().lower().removeprefix("www.")
    titles = [str(t).strip() for t in person_titles if t and str(t).strip()][:12]
    if not titles:
        titles = ["marketing"]
    per = min(max(1, int(per_page)), 100)
    body: dict[str, Any] = {
        "page": 1,
        "per_page": per,
        "q_organization_domains_list": [dom],
        "person_titles": titles,
    }
    return _apollo_post_json("/mixed_people/api_search", json_body=body)


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
        push_human_ui_activity_once(
            db,
            run_id,
            "apollo_not_configured",
            "Apollo: на сервере не задан ключ API — запросы к Apollo не отправлялись. "
            "Добавьте ключ в настройки бэкенда и при необходимости перезапустите сбор.",
        )
        return None
    ctx = get_effective_context(run)
    hints = apollo_llm_hints_for_run(run_id, run)
    if hints:
        tags, _ = hints
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: теги для поиска организаций заданы через LLM под формат Apollo (keyword tags).",
        )
        push_human_ui_activity(db, run_id, f"Apollo LLM → tags: {', '.join(tags[:16])}.")
    else:
        tags = keyword_tags_from_context(ctx)
        push_human_ui_activity(
            db,
            run_id,
            f"Apollo: теги (эвристика, без LLM или сбой LLM): {', '.join(tags[:8])}.",
        )
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
    run_setup = getattr(run, "run_setup", None)
    org_filters = apollo_org_filters_from_run_setup(run_setup)
    geo_desc = ", ".join(org_filters["locations"]) if org_filters["locations"] else "не задан"
    size_desc = ", ".join(org_filters["num_employees_ranges"])
    push_human_ui_activity(
        db,
        run_id,
        f"Apollo: гео-фильтр — {geo_desc}; диапазон размера компании — {size_desc}.",
    )
    push_human_ui_activity(db, run_id, "Apollo: запрос поиска организаций…")
    try:
        data = search_organizations_json(
            tags,
            page=1,
            per_page=per_page,
            locations=org_filters["locations"],
            num_employees_ranges=org_filters["num_employees_ranges"],
        )
    except Exception:
        logger.exception("Apollo organization search failed; falling back to LLM")
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: ошибка поиска организаций — будет использован другой сценарий сбора.",
        )
        return None

    orgs = _organizations_from_apollo_search_payload(data)
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
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: в ответе нет новых организаций — будет использован другой сценарий сбора.",
        )
        return None
    push_human_ui_activity(db, run_id, f"Apollo: из поиска организаций добавлено компаний: {len(rows)}.")
    return {"companies": rows}


def try_find_contacts_via_apollo(db, run_id: int, run, step_input: dict) -> dict[str, Any] | None:
    """
    Returns {"contacts": [...]} when Apollo should handle find_contacts.

    - ``None`` only if Apollo is **not** configured (caller may use LLM).
    - If Apollo **is** configured, always returns a dict (possibly empty) — no LLM fallback for contact search.
    """
    if not apollo_configured():
        push_human_ui_activity_once(
            db,
            run_id,
            "apollo_not_configured",
            "Apollo: на сервере не задан ключ API — запросы к Apollo не отправлялись. "
            "Добавьте ключ в настройки бэкенда и при необходимости перезапустите сбор.",
        )
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
        logger.info("Apollo find_contacts: no grounded companies — returning empty contacts (LLM not used)")
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: нет компаний для поиска контактов (после фильтра).",
        )
        return {"contacts": []}

    ctx = get_effective_context(run)
    hints = apollo_llm_hints_for_run(run_id, run)
    if hints:
        _, titles = hints
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: должности для поиска людей — из того же LLM-ответа, что и теги организаций.",
        )
    else:
        titles = person_titles_from_context(ctx)
    per_co = max(1, int(settings.APOLLO_MAX_PEOPLE_PER_COMPANY))
    cap = max(1, int(settings.APOLLO_MAX_PEOPLE_TOTAL))
    contacts: list[dict[str, Any]] = []
    remaining = cap

    logger.info(
        "Apollo find_contacts run_id=%s: starting — %d company row(s), role hints=%d, cap=%d (people API + bulk_match)",
        run_id,
        len(grounded),
        len(titles),
        cap,
    )
    push_human_ui_activity(
        db,
        run_id,
        f"Apollo: поиск контактов — компаний: {len(grounded)}, подсказок по ролям: {len(titles)}, лимит: {cap}.",
    )

    try:
        for co in grounded:
            if remaining <= 0:
                break
            name = (co.get("name") or "").strip() or "—"
            website = (co.get("website") or "").strip()
            domain = domain_from_website(website)
            if not domain:
                push_human_ui_activity(
                    db,
                    run_id,
                    f"Apollo: skip contact search for «{name}» — no domain derived from website (fix URL or retry after editing).",
                )
                continue

            page_size = min(per_co, 25, remaining)
            pdata = search_people_json(domain, titles, per_page=page_size)
            people = pdata.get("people")
            if not isinstance(people, list) or not people:
                # B-274 second pass: the run's narrow title list found nobody at this company —
                # retry once with the standing hiring-side titles before giving up. Never falls back
                # to an LLM: empty from Apollo means empty (the LLM used to invent a plausible
                # person + address here, and a catch-all domain then verified it).
                extra_titles = fallback_person_titles(titles)
                if extra_titles:
                    pdata = search_people_json(domain, extra_titles, per_page=page_size)
                    people = pdata.get("people")
                if isinstance(people, list) and people:
                    push_human_ui_activity(
                        db,
                        run_id,
                        f"Apollo: «{name}» — по должностям рана никого; нашли вторым проходом "
                        f"(head of people / recruiting / talent).",
                    )
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
                # B-275: keep Apollo's own linkedin_url on the contact and cross-check the surname
                # against it — Apollo returns a corrupted last name often enough ("Stephen
                # Gamescom" for Stephen Bell) that a mismatch must reach the human, not the letter.
                contacts.append(
                    annotate_surname_check(
                        {
                            "company": name,
                            "website": website,
                            "name": full,
                            "role": role,
                            "email": email,
                            "linkedin": (m.get("linkedin_url") or "").strip() or None,
                            "source": "apollo",
                        }
                    )
                )
                remaining -= 1
                if remaining <= 0:
                    break
    except Exception:
        logger.exception("Apollo find_contacts failed — returning empty contacts (LLM not used)")
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: ошибка при поиске людей — контакты не получены.",
        )
        return {"contacts": []}

    if not contacts:
        logger.info("Apollo find_contacts: no people matched — returning empty contacts (LLM not used)")
        push_human_ui_activity(
            db,
            run_id,
            "Apollo: в ответе API нет контактов для этого запуска.",
        )
        return {"contacts": []}
    with_email = sum(
        1
        for c in contacts
        if isinstance(c, dict) and "@" in str(c.get("email") or "").strip().lower()
    )
    logger.info(
        "Apollo find_contacts run_id=%s: OK — %d contact row(s) from Apollo (%d with email in payload)",
        run_id,
        len(contacts),
        with_email,
    )
    push_human_ui_activity(
        db,
        run_id,
        f"Apollo: готово — контактов: {len(contacts)}, с email в ответе: {with_email}.",
    )
    return {"contacts": contacts}
