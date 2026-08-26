"""Firmographics providers (Phase 6): resolve a company's employee_count / OKVED / INN to drive
the deterministic ICP size-filter. Priority-ordered fallback like llm_gateway; each provider is
config-gated like llm_gateway. A provider returns a normalized dict or None (not configured
OR no result); exceptions are swallowed so enrichment never breaks.

Normalized return shape:
    {"employee_count": int|None, "okved": str|None, "okveds": list[str], "inn": str|None,
     "region": str|None, "revenue": float|None, "source": str}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def dadata_configured() -> bool:
    return bool((settings.DADATA_API_KEY or "").strip())


def _provider_priority() -> list[str]:
    raw = (settings.FIRMOGRAPHICS_PROVIDER_PRIORITY or "").strip()
    order = [p.strip() for p in raw.split(",") if p.strip()]
    return order or ["dadata", "egrul_free"]


def _normalized(employee_count=None, okved=None, okveds=None, inn=None, region=None,
                revenue=None, source="") -> dict[str, Any]:
    return {
        "employee_count": employee_count if isinstance(employee_count, int) else None,
        "okved": okved or None,
        "okveds": [c for c in (okveds or ([okved] if okved else [])) if c],
        "inn": inn or None,
        "region": region or None,
        "revenue": revenue if isinstance(revenue, (int, float)) else None,
        "source": source,
    }


def _dadata_lookup(name: str, website: str = "", inn: str = "") -> dict[str, Any] | None:
    """Dadata find-party (by INN if known, else by name). employee_count needs the paid tier;
    when the field is absent we still return OKVED/INN so other ICP criteria can apply."""
    if not dadata_configured():
        return None
    query = (inn or name or "").strip()
    if not query:
        return None
    try:
        resp = httpx.post(
            "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
            if inn else
            "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party",
            headers={
                "Authorization": f"Token {settings.DADATA_API_KEY.strip()}",
                "Content-Type": "application/json",
            },
            json={"query": query, "count": 1},
            timeout=settings.DADATA_HTTP_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        suggestions = resp.json().get("suggestions") or []
    except Exception as e:
        logger.warning(f"Dadata firmographics lookup failed for {name!r}: {e}")
        return None
    if not suggestions:
        return None
    data = suggestions[0].get("data") or {}
    emp = data.get("employee_count")
    okved = data.get("okved")
    okveds = [o.get("okved") for o in (data.get("okveds") or []) if isinstance(o, dict) and o.get("okved")]
    addr = data.get("address") or {}
    region = (addr.get("data") or {}).get("region") if isinstance(addr, dict) else None
    finance = data.get("finance") or {}
    revenue = finance.get("income") if isinstance(finance, dict) else None
    return _normalized(
        employee_count=emp if isinstance(emp, int) else None,
        okved=okved, okveds=okveds or ([okved] if okved else []),
        inn=data.get("inn"), region=region, revenue=revenue, source="dadata",
    )


def _egrul_free_lookup(name: str, website: str = "", inn: str = "") -> dict[str, Any] | None:
    """Free best-effort fallback via the egrul.itsoft.ru FNS mirror (JSON by INN, no key).
    Requires an INN; mirror has no SLA, so failures are silent and just yield None."""
    if not inn:
        return None  # mirror is INN-keyed; without an INN we can't use it
    try:
        resp = httpx.get(f"https://egrul.itsoft.ru/{inn}.json", timeout=8.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.info(f"egrul_free lookup miss for INN {inn}: {e}")
        return None
    # Shape varies; pull headcount/OKVED defensively.
    emp = data.get("СЧР") or data.get("employee_count") or data.get("average_headcount")
    try:
        emp = int(emp) if emp is not None else None
    except (TypeError, ValueError):
        emp = None
    okved = data.get("ОКВЭД") or data.get("okved")
    return _normalized(employee_count=emp, okved=okved, inn=inn, source="egrul_free")


_PROVIDERS = {"dadata": _dadata_lookup, "egrul_free": _egrul_free_lookup}


def firmographics_configured() -> bool:
    """Any firmographics provider usable? Dadata needs a key; egrul_free is keyless but INN-gated."""
    return dadata_configured() or "egrul_free" in _provider_priority()


def lookup_firmographics(name: str, *, website: str = "", inn: str = "") -> dict[str, Any] | None:
    """Try providers in priority order; first non-None wins. None = nothing resolved."""
    for pid in _provider_priority():
        fn = _PROVIDERS.get(pid)
        if not fn:
            continue
        try:
            out = fn(name, website=website, inn=inn)
        except Exception as e:
            logger.warning(f"Firmographics provider {pid} raised for {name!r}: {e}")
            out = None
        if out:
            # carry the INN forward so a later keyless provider could chain off a Dadata-found INN
            if not inn and out.get("inn"):
                inn = out["inn"]
            return out
    return None
