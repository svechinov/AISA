"""
Map full run outreach context → Apollo.io search parameters via one LLM JSON call.

Heuristic tokenization (keyword_tags_from_context) is too lossy: broad tokens can match
museum gift shops, tourism retail, etc. This runs **before** Apollo org/people search when
LLM keys are configured, to reduce wasted Apollo credits.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.services.llm_gateway import complete_prompt_json_object, llm_configured
from app.services.run_context_service import build_master_prompt_text, coalesce_str, get_effective_context

logger = logging.getLogger(__name__)

_TTL_SEC = 600.0
_cache: dict[int, tuple[tuple[list[str], list[str]], float]] = {}


def _sanitize_tags(raw: Any, *, max_n: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        t = re.sub(r"[\s,;|]+", " ", str(x or "").strip())
        t = re.sub(r"^[\-–—•]+|[\-–—•]+$", "", t).strip()
        if len(t) < 2 or len(t) > 48:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= max_n:
            break
    return out


def _sanitize_titles(raw: Any, *, max_n: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        t = str(x or "").strip()
        if len(t) < 2 or len(t) > 80:
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= max_n:
            break
    return out


def apollo_llm_hints_for_run(run_id: int, run) -> tuple[list[str], list[str]] | None:
    """
    One LLM call → (organization_keyword_tags for POST /organizations/search,
    person_titles for POST /mixed_people/api_search).

    Returns None if LLM unavailable or the call fails — callers fall back to heuristics.
    Cached per run_id for a short TTL to avoid duplicate calls in collect + find.
    """
    if not llm_configured():
        return None

    now = time.monotonic()
    ent = _cache.get(run_id)
    if ent is not None:
        (tags, titles), t0 = ent
        if now - t0 < _TTL_SEC and (tags or titles):
            return tags, titles

    ctx = get_effective_context(run)
    brief = build_master_prompt_text(ctx)
    mp = coalesce_str(getattr(run, "master_prompt", None))
    block = f"{mp}\n\n---\n{brief}" if mp else brief

    prompt = (
        "You translate an outreach campaign brief into parameters for Apollo.io B2B search.\n\n"
        "Apollo organization search uses SHORT keyword tags (array q_organization_keyword_tags). "
        "Tags must describe the KIND of company to find (e.g. manufacturers, OEM, brand owners, "
        "licensing partners, private-label producers). "
        "Do NOT optimize for museum stores, museum gift shops, tourist gift retail, or cultural "
        "institution boutiques unless the user explicitly asks for those. "
        "If the brief mentions licensing or co-branded products, still prefer manufacturers and "
        "brand owners over venue retail.\n\n"
        "Return ONLY valid JSON (no markdown) with exactly this shape:\n"
        '{"organization_keyword_tags": ["...", "..."], "person_titles": ["...", "..."]}\n\n'
        "Rules:\n"
        "- organization_keyword_tags: 5 to 12 strings, each 2–48 characters, no commas inside one string.\n"
        "- person_titles: up to 12 job title phrases for decision-makers (licensing, partnerships, "
        "product, business development, wholesale).\n\n"
        "Campaign context:\n"
        f"{block}\n"
    )

    try:
        out = complete_prompt_json_object(prompt)
    except Exception:
        logger.exception("apollo_llm_hints: LLM call failed run_id=%s", run_id)
        return None

    if not isinstance(out, dict):
        return None

    raw_tags = out.get("organization_keyword_tags")
    if raw_tags is None:
        raw_tags = out.get("keyword_tags")
    tags = _sanitize_tags(raw_tags, max_n=20)
    titles = _sanitize_titles(out.get("person_titles"), max_n=12)

    if not tags:
        logger.warning("apollo_llm_hints: empty organization_keyword_tags run_id=%s", run_id)
        return None

    if not titles:
        titles = [
            "licensing",
            "business development",
            "product",
            "partnerships",
            "sales",
            "marketing",
        ]

    _cache[run_id] = ((tags, titles), now)
    return tags, titles


def invalidate_apollo_llm_hints_cache(run_id: int) -> None:
    _cache.pop(run_id, None)
