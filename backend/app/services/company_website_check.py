"""
Annotate collected company rows with llm_hallucination (invalid/unreachable website).

Uses httpx for HTTP checks; runs concurrently in a thread pool.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_UA = "Mozilla/5.0 (compatible; AiBizOsCollect/1.0; +https://github.com/)"

DEFAULT_TIMEOUT_SEC = 8.0
DEFAULT_MAX_WORKERS = 8

_SUSPICIOUS_WEBSITE_SUBSTR = (
    "example.com",
    "example.org",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "test.invalid",
)


def normalize_company_website_url(raw: str) -> str | None:
    """Return a usable http(s) URL, or None if the string cannot be interpreted as a site URL."""
    s = (raw or "").strip()
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    try:
        u = httpx.URL(s)
    except Exception:
        return None
    host = (u.host or "").strip().lower()
    if not host or "." not in host:
        return None
    return str(u)


def basic_company_row_is_hallucination(name: str, website: str) -> bool:
    """True when name/website are empty, host invalid, or URL matches obvious placeholders."""
    if not (name or "").strip() or not (website or "").strip():
        return True
    wlow = website.lower()
    host = re.sub(r"^https?://", "", wlow, flags=re.I).split("/")[0].split("@")[-1]
    if "." not in host or host.startswith("."):
        return True
    if any(s in wlow for s in _SUSPICIOUS_WEBSITE_SUBSTR):
        return True
    return False


def _single_get(url: str, *, timeout_sec: float) -> tuple[bool, str]:
    timeout = httpx.Timeout(timeout_sec, connect=min(6.0, timeout_sec * 0.75))
    headers = {"User-Agent": _DEFAULT_UA, "Accept": "*/*"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, verify=True) as client:
            with client.stream("GET", url) as response:
                status = response.status_code
                for chunk in response.iter_bytes(1024):
                    break
        return True, f"http_status={status}"
    except httpx.HTTPError as e:
        return False, f"http_error={type(e).__name__}:{e!s}"[:500]
    except Exception as e:
        return False, f"error={type(e).__name__}:{e!s}"[:500]


def check_website_reachable(url: str, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> tuple[bool, str]:
    """
    Return (True, detail) if we get an HTTP response (status line received after redirects).
    Return (False, detail) on DNS/connect/TLS/timeout.
    If https:// fails before any response, tries http:// once (legacy / misconfigured hosts).
    """
    ok, detail = _single_get(url, timeout_sec=timeout_sec)
    if ok:
        return True, detail
    if url.startswith("https://"):
        http_url = "http://" + url.removeprefix("https://")
        ok2, d2 = _single_get(http_url, timeout_sec=timeout_sec)
        if ok2:
            return True, f"{d2} scheme=http_fallback"
        return False, f"{detail}; http_fallback={d2}"
    return False, detail


def annotate_companies_list_with_llm_flags(
    companies: list[dict[str, Any]],
    *,
    run_id: int | None = None,
    timeout_sec: float | None = None,
    max_workers: int | None = None,
    http_check_enabled: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Return a new list of company dicts with boolean llm_hallucination set.
    Preserves extra keys from each input dict where possible.
    """
    if not companies:
        return []

    timeout_sec = float(timeout_sec if timeout_sec is not None else settings.COLLECT_COMPANIES_HTTP_TIMEOUT_SEC)
    max_workers = int(max_workers if max_workers is not None else settings.COLLECT_COMPANIES_HTTP_MAX_WORKERS)
    http_check_enabled = (
        bool(settings.COLLECT_COMPANIES_HTTP_CHECK_ENABLED)
        if http_check_enabled is None
        else bool(http_check_enabled)
    )

    rid = f"run_id={run_id}" if run_id is not None else "run_id=?"

    out: list[dict[str, Any]] = []
    http_indices: list[int] = []

    for c in companies:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        website = (c.get("website") or "").strip()
        row = {**c, "name": name or "—", "website": website}
        if basic_company_row_is_hallucination(name, website):
            row["llm_hallucination"] = True
            out.append(row)
            logger.info(
                "collect_companies: llm_flag %s name=%r basic_invalid website=%r",
                rid,
                name or "—",
                website,
            )
            continue
        row["llm_hallucination"] = False
        out.append(row)
        if http_check_enabled:
            http_indices.append(len(out) - 1)

    if not http_check_enabled or not http_indices:
        return out

    def work(list_index: int) -> tuple[int, bool, str]:
        row = out[list_index]
        name = str(row.get("name") or "").strip()
        website = str(row.get("website") or "").strip()
        url = normalize_company_website_url(website)
        if not url:
            line = f"collect_companies: llm_flag {rid} hallucination name={name!r} reason=bad_url raw={website!r}"
            return list_index, True, line
        ok, detail = check_website_reachable(url, timeout_sec=timeout_sec)
        hallucination = not ok
        if hallucination:
            line = f"collect_companies: llm_flag {rid} hallucination name={name!r} url={url} {detail}"
        else:
            line = f"collect_companies: llm_flag {rid} ok name={name!r} url={url} {detail}"
        return list_index, hallucination, line

    workers = max(1, min(max_workers, len(http_indices)))
    results: list[tuple[int, bool, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, idx) for idx in http_indices]
        for fut in as_completed(futs):
            results.append(fut.result())

    for list_index, hallucination, line in sorted(results, key=lambda x: x[0]):
        logger.info(line)
        out[list_index]["llm_hallucination"] = hallucination

    return out


def collect_companies_annotate_llm_flags(raw: dict, *, run_id: int | None) -> dict:
    """Normalize LLM JSON and annotate every company row with llm_hallucination."""
    companies = raw.get("companies") if isinstance(raw, dict) else None
    if not isinstance(companies, list):
        return {"companies": []}
    annotated = annotate_companies_list_with_llm_flags(companies, run_id=run_id)
    n_hall = sum(1 for x in annotated if x.get("llm_hallucination"))
    logger.info(
        "collect_companies: summary %s rows=%s llm_hallucination=%s",
        f"run_id={run_id}" if run_id is not None else "run_id=?",
        len(annotated),
        n_hall,
    )
    return {"companies": annotated}
