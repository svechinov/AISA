"""Web search provider (R4): pluggable snippet search, Yandex primary + Tavily fallback.

Yandex Cloud Search API queries the real yandex.ru index — it surfaces VK / Telegram / OK /
regional RU press that the US-indexed Tavily is blind to (pilot: «Шаройкина Воркутауголь» found
0 via Tavily, 11 via Yandex). Config-gated like llm_gateway; priority fallback. A provider
returns [] on no-result/not-configured/error so callers can fall through; never raises.

Normalized return: list[{"title": str, "url": str, "snippet": str}].
"""

from __future__ import annotations

import base64
import logging
import xml.etree.ElementTree as ET

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_YANDEX_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"


def yandex_search_configured() -> bool:
    return bool((settings.YANDEX_SEARCH_API_KEY or "").strip() and (settings.YANDEX_FOLDER_ID or "").strip())


def _provider_priority() -> list[str]:
    raw = (settings.SEARCH_PROVIDER_PRIORITY or "").strip()
    order = [p.strip() for p in raw.split(",") if p.strip()]
    return order or ["yandex", "tavily"]


def _parse_yandex_xml(raw_b64: str) -> list[dict]:
    try:
        xml = base64.b64decode(raw_b64).decode("utf-8", "replace")
        root = ET.fromstring(xml)
    except Exception as e:
        logger.warning(f"Yandex search: XML parse failed: {e}")
        return []
    out: list[dict] = []
    for doc in root.iter("doc"):
        url = (doc.findtext("url") or "").strip()
        title_el = doc.find("title")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        passages = [" ".join(p.itertext()).strip() for p in doc.iter("passage")]
        if url:
            out.append({"title": title, "url": url, "snippet": " ".join(passages).strip()})
    return out


def _yandex_search(query: str, *, max_results: int, max_passages: int) -> list[dict]:
    if not yandex_search_configured():
        return []
    body = {
        "query": {"searchType": "SEARCH_TYPE_RU", "queryText": query[:400],
                  "familyMode": "FAMILY_MODE_NONE"},
        "groupSpec": {"groupMode": "GROUP_MODE_FLAT", "groupsOnPage": max(1, min(max_results, 100)),
                      "docsInGroup": 1},
        "maxPassages": max(1, min(max_passages, 5)),
        "region": settings.YANDEX_SEARCH_REGION or "225",
        "folderId": settings.YANDEX_FOLDER_ID.strip(),
        "responseFormat": "FORMAT_XML",
    }
    try:
        r = httpx.post(
            _YANDEX_ENDPOINT,
            headers={"Authorization": f"Api-Key {settings.YANDEX_SEARCH_API_KEY.strip()}",
                     "Content-Type": "application/json"},
            json=body, timeout=settings.YANDEX_HTTP_TIMEOUT_SEC,
        )
        if r.status_code != 200:
            logger.warning(f"Yandex search non-200 ({r.status_code}): {r.text[:200]}")
            return []
        raw = r.json().get("rawData", "")
    except Exception as e:
        logger.warning(f"Yandex search request failed: {e}")
        return []
    return _parse_yandex_xml(raw)[:max_results]


def _tavily_search(query: str, *, max_results: int, max_passages: int) -> list[dict]:
    from app.services.tavily_osint import get_tavily_client

    client = get_tavily_client()
    if not client:
        return []
    try:
        resp = client.search(query=query, search_depth="basic", max_results=max_results)
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return []
    out: list[dict] = []
    for r in resp.get("results", []):
        url = (r.get("url") or "").strip()
        if url:
            out.append({"title": (r.get("title") or "").strip(),
                        "url": url, "snippet": (r.get("content") or "").strip()})
    return out


def tavily_search_configured() -> bool:
    import os

    return bool((os.environ.get("TAVILY_API_KEY") or "").strip())


def search_configured() -> bool:
    """True only when a provider in the priority list is actually usable (has credentials).
    A provider merely being listed must not count: callers gate OSINT dossier generation on
    this, and an ungated empty corpus lets the LLM fabricate dossiers from nothing."""
    for pid in _provider_priority():
        if pid == "yandex" and yandex_search_configured():
            return True
        if pid == "tavily" and tavily_search_configured():
            return True
    return False


def search_web(query: str, *, max_results: int = 8, max_passages: int = 5) -> list[dict]:
    """Snippet search in priority order; first provider returning hits wins. [] if all miss."""
    query = (query or "").strip()
    if not query:
        return []
    # Resolved per call (not a module-level dict) so test monkeypatches of the adapters apply.
    providers = {"yandex": _yandex_search, "tavily": _tavily_search}
    for pid in _provider_priority():
        fn = providers.get(pid)
        if not fn:
            continue
        hits = fn(query, max_results=max_results, max_passages=max_passages)
        if hits:
            logger.info(f"search_web: {len(hits)} hits via {pid} for {query[:60]!r}")
            return hits
    return []


_DOMAIN_SKIP = (
    # RU aggregators/news/social
    "list-org", "rusprofile", "hh.ru", "vk.com", "t.me", "ok.ru", "youtube", "wikipedia",
    "rbc.ru", "kommersant", "tadviser", "zachestnyibiznes", "sbis.ru", "audit-it", "2gis",
    "yell.ru", "spark-interfax", "gov.ru", "interfax", "vedomosti", "cdn", "yandex", "google",
    "facebook", "instagram", "telegram", "avito", "zoon", "flamp",
    # Global aggregators/directories/stores — never a company's own site
    "linkedin", "crunchbase", "glassdoor", "indeed", "apollo.io", "pitchbook", "zoominfo",
    "bloomberg", "reuters", "techcrunch", "medium.com", "github.com", "x.com", "twitter",
    "apps.apple", "play.google", "steampowered", "itch.io", "mobygames",
)


def resolve_company_domain(name: str, language: str = "English") -> str | None:
    """Find a company's official site domain via search (unblocks discovery for sourced companies
    that arrive without a website). Returns a bare domain or None. Skips aggregators/news/social.
    The query follows the campaign language (RU query steers Yandex into Runet)."""
    from urllib.parse import urlparse

    name = (name or "").strip()
    if not name:
        return None
    if (language or "").strip().lower() == "russian":
        query = f"{name} официальный сайт"
    else:
        query = f'"{name}" official website'
    for hit in search_web(query, max_results=6, max_passages=1):
        host = (urlparse(hit.get("url", "")).netloc or "").lower().replace("www.", "")
        if host and "." in host and not any(s in host for s in _DOMAIN_SKIP):
            return host
    return None


def search_corpus(query: str, *, max_results: int = 5, max_passages: int = 5) -> str:
    """Concatenated title+snippet corpus for LLM consumption (replaces ad-hoc snippet joins)."""
    return "\n".join(
        f"[{h['title']}] {h['snippet']} ({h['url']})" for h in search_web(
            query, max_results=max_results, max_passages=max_passages)
    )
