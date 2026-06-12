"""Phase 4 (Stage 1b): company sources — rating-page extractor + tender-intent search.

Three entry points, all returning [{name, website?, note?}] for append_companies_to_run:
- extract_companies_from_url:      given a rating/list URL → Tavily Extract → LLM parses companies.
- extract_companies_by_criterion:  given a text criterion → Tavily search finds list/rating URLs
                                   → extract the top ones.
- extract_companies_from_tenders:  search procurement domains for training purchases → LLM pulls
                                   the BUYER companies (стронгest intent signal: они уже покупают
                                   обучение). The tender context goes into note.

Scoring is NOT done here — appended companies flow through the existing AI-fit judge and the
ICP gate in enrich (one scoring surface, no duplicate).
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.llm_gateway import complete_prompt_json_object
from app.services.prompt_builder import build_prompt
from app.services.tavily_osint import get_tavily_client
from app.utils.env_utils import env_int

logger = logging.getLogger(__name__)

# Procurement platforms with reasonable search-engine indexing.
TENDER_SITES = ("zakupki.gov.ru", "b2b-center.ru", "roseltorg.ru", "sberbank-ast.ru")

COMPANIES_SCHEMA = {
    "companies": [
        {
            "name": "company legal/brand name (the BUYER for tenders, never the platform)",
            "website": "company site if visible in the text, else empty string",
            "note": "short evidence: why this company is in the list / what it purchases",
        }
    ]
}


def _page_char_limit() -> int:
    return env_int("SOURCE_EXTRACT_MAX_CHARS", 28_000, min_value=1000)


def _max_companies() -> int:
    return env_int("SOURCE_EXTRACT_MAX_COMPANIES", 60, min_value=1)


def _parse_companies_from_text(text: str, *, task_hint: str) -> list[dict[str, Any]]:
    """One LLM call: page text → normalized company list."""
    task = (
        "Extract REAL companies from the page text below.\n"
        f"{task_hint}\n"
        "Rules: skip the page's own brand/platform, navigation, ads and people names; "
        "no duplicates; keep original company names (Russian ok); website only if it appears "
        "in the text (do not guess); note = one short evidence phrase from the text."
    )
    prompt = build_prompt(
        task=task,
        data={"page_text": text[: _page_char_limit()]},
        rules=[],
        output_schema=COMPANIES_SCHEMA,
    )
    out = complete_prompt_json_object(prompt)
    raw = out.get("companies") if isinstance(out, dict) else None
    companies: list[dict[str, Any]] = []
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        companies.append(
            {
                "name": name,
                "website": str(c.get("website") or "").strip(),
                "note": str(c.get("note") or "").strip(),
            }
        )
        if len(companies) >= _max_companies():
            break
    return companies


def _extract_page_text(url: str) -> str:
    """Tavily Extract for one URL; empty string when nothing usable came back."""
    client = get_tavily_client()
    if not client:
        raise ValueError("Tavily API key not configured")
    resp = client.extract(urls=[url])
    for item in resp.get("results", []):
        content = item.get("raw_content") or item.get("content") or ""
        if content.strip():
            return content
    failed = resp.get("failed_results") or []
    if failed:
        logger.warning(f"Tavily extract failed for {url}: {failed[:1]}")
    return ""


def extract_companies_from_url(url: str, *, hint: str = "") -> list[dict[str, Any]]:
    """Mode «дан URL»: rating/list page → companies."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http(s)://")
    text = _extract_page_text(url)
    if not text:
        return []
    task_hint = (
        "The text is a rating / industry list page — extract the LISTED companies in order."
        + (f" Focus: {hint}." if hint else "")
    )
    return _parse_companies_from_text(text, task_hint=task_hint)


def discover_list_urls(criterion: str, *, max_urls: int = 3) -> list[str]:
    """Mode «дан критерий», step 1: find rating/list pages for the criterion (Yandex-primary)."""
    from app.services.search_service import search_web

    urls: list[str] = []
    for hit in search_web(f"{criterion} рейтинг список компаний топ", max_results=max(3, max_urls * 2)):
        u = hit.get("url") or ""
        if u and "youtube" not in u and "vk.com" not in u and u not in urls:
            urls.append(u)
        if len(urls) >= max_urls:
            break
    return urls


def extract_companies_by_criterion(criterion: str, *, max_urls: int = 2) -> dict[str, Any]:
    """Mode «дан критерий»: search → extract the top list pages → merged companies."""
    criterion = (criterion or "").strip()
    if not criterion:
        raise ValueError("criterion must not be empty")
    urls = discover_list_urls(criterion, max_urls=max_urls)
    companies: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_urls: list[str] = []
    for url in urls:
        try:
            found = extract_companies_from_url(url, hint=criterion)
        except Exception as e:
            logger.warning(f"Criterion extract failed for {url}: {e}")
            continue
        if found:
            used_urls.append(url)
        for c in found:
            key = c["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            companies.append(c)
            if len(companies) >= _max_companies():
                return {"companies": companies, "urls": used_urls}
    return {"companies": companies, "urls": used_urls}


def extract_companies_from_tenders(query: str, *, max_results: int = 8) -> dict[str, Any]:
    """Tender intent: search procurement platforms for training purchases → buyer companies.

    The buyers are companies ALREADY purchasing training — the hottest intent signal we have.
    MVP: search-engine-indexed tender pages via Tavily (no platform APIs / anti-bot fights).
    """
    query = (query or "").strip() or "закупка проведение тренинга обучение руководителей"
    from app.services.search_service import search_web

    site_filter = " OR ".join(f"site:{s}" for s in TENDER_SITES)
    hits = search_web(f"{query} ({site_filter})", max_results=max_results, max_passages=5)
    chunks: list[str] = []
    urls: list[str] = []
    for h in hits:
        text = (h.get("snippet") or "").strip()
        u = h.get("url") or ""
        if text:
            chunks.append(f"--- TENDER PAGE ({u}) ---\n{h.get('title','')}\n{text}")
            urls.append(u)
    if not chunks:
        return {"companies": [], "urls": []}

    companies = _parse_companies_from_text(
        "\n\n".join(chunks),
        task_hint=(
            "The text contains procurement/tender pages. Extract the CUSTOMER (заказчик) "
            "companies that are BUYING training/education services — never the platform, "
            "never suppliers. note = what training they purchase (from the tender subject)."
        ),
    )
    return {"companies": companies, "urls": urls}
