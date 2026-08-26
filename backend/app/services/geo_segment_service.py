"""Geo-segment resolver (B-063): recipient location -> email closing-paragraph segment
(ru-email-canon.md §2.2) + the Malindi/ex-CIS filter (decision 3, 2026-07-15 handoff).

B-071 (data-driven personas, decision 8/9): the keyword tables (Cyprus/city/ex-CIS/address/
negation) and the Malindi modifier are no longer module constants — they live in
persona.geo_map_json (app.services.persona_service.ALEXEY_GEO_MAP_JSON holds the alexey persona's
byte-identical migration of the old CYPRUS_KEYWORDS/CITY_SEGMENT_KEYWORDS/EX_CIS_KEYWORDS/
ADDRESS_CONTEXT_KEYWORDS/NEGATION_CONTEXT_KEYWORDS). Segments are the persona's string keys
(paphos/limassol/larnaca_nicosia/cyprus_other/outside for alexey), not the old global int 1-5.
The engine below (prefix-boundary regex, address-context gate, cascade) is generic; only the data
is Cyprus/alexey-specific now.

Pure function reading already-persisted OSINT data — no network calls, never raises. Cascade
(decision 2): recipient's own location (pers.person_osint.recipient_location) -> company office
city (company_evidence facts / run_company extra KV osint_dossier text) -> company country text
from the same sources. Cyprus confirmed without a city -> geo_map_json.cyprus_no_city_segment;
not Cyprus or nothing recognizable -> geo_map_json.default_segment.

Malindi filter (decision 3, naming/premise updated 2026-07-16): the Wednesday iT_Party at
Malindi (officially Cyprus_iT Networking) is an expat gathering, mostly IT crowd; without
evidence of an ex-CIS background we do not reference it (conservative default, confirmed by
Алексей 16.07). Unclear/ambiguous data always resolves to the SAFE default (persona's
default_segment, malindi=False) rather than guessing wrong — a misplaced iT_Party callout or a
wrong city reads worse than a generic closing.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.contact import Contact

_ADDRESS_CONTEXT_WINDOW = 60  # chars either side of a city hit to look for a context marker

# Compiled keyword patterns, cached per persona (keyed by persona.id, else .slug, else identity)
# so the regex compilation (finding #6-safe boundary alternation) happens once per persona.
_persona_pattern_cache: dict[Any, dict[str, Any]] = {}


def _boundary_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Prefix-anchored alternation: a word boundary must precede the keyword, but any suffix may
    follow (so Russian case endings still match: 'лимасол' -> 'лимасоле'/'лимасола'). This kills
    the mid-word substring hits that plagued naive `kw in text` — 'рф' inside 'серфинг'/
    'перформанс', 'баку' inside 'табаку' (finding #6) — while keeping inflection tolerance."""
    alts = "|".join(sorted((re.escape(k) for k in keywords), key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + alts + r")", re.IGNORECASE | re.UNICODE)


def _text_has_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Prefix-anchored presence test (used for the ex-CIS heuristic)."""
    return bool(_boundary_pattern(keywords).search(text or ""))


def _compiled_patterns(persona: Any) -> dict[str, Any]:
    """Compile (and cache) persona.geo_map_json's keyword tables into regex patterns."""
    cache_key = getattr(persona, "id", None) or getattr(persona, "slug", None) or id(persona)
    cached = _persona_pattern_cache.get(cache_key)
    if cached is not None:
        return cached

    geo_map = persona.geo_map_json or {}
    city_segments: dict[str, list[str]] = geo_map.get("city_segments") or {}
    compiled = {
        "city_patterns": {
            seg: _boundary_pattern(tuple(kws)) for seg, kws in city_segments.items()
        },
        "cyprus_pattern": _boundary_pattern(tuple(geo_map.get("cyprus_keywords") or ())),
        "address_pattern": _boundary_pattern(tuple(geo_map.get("address_context_keywords") or ())),
        "negation_pattern": _boundary_pattern(tuple(geo_map.get("negation_context_keywords") or ())),
    }
    _persona_pattern_cache[cache_key] = compiled
    return compiled


def _segment_from_text(text: str, persona: Any) -> str | None:
    """Recipient's OWN location text -> segment key (prefix-anchored), or None. Used only for the
    person's own location field, which is already a location — no address-context gate needed."""
    if not text:
        return None
    patterns = _compiled_patterns(persona)
    for segment, pattern in patterns["city_patterns"].items():
        if pattern.search(text):
            return segment
    if patterns["cyprus_pattern"].search(text):
        return (persona.geo_map_json or {}).get("cyprus_no_city_segment", "cyprus_other")
    return None


def _near_address_context(text: str, start: int, end: int, persona: Any) -> bool:
    patterns = _compiled_patterns(persona)
    lo = max(0, start - _ADDRESS_CONTEXT_WINDOW)
    hi = min(len(text), end + _ADDRESS_CONTEXT_WINDOW)
    window = text[lo:hi]
    if patterns["negation_pattern"].search(window):
        return False  # closed/former/previous location — not where the recipient is now
    return bool(patterns["address_pattern"].search(window))


def _segment_from_company_text(text: str, persona: Any) -> str | None:
    """Company-dossier free text -> segment, with the address-context guard (finding #5).

    A specific-city segment is trusted only when the city sits next to an address/office marker.
    If cities from >1 distinct segments appear in address context, the office location is
    ambiguous -> fall back to the Cyprus-no-city segment when Cyprus is mentioned, else None.
    A city mentioned WITHOUT address context is ignored; a bare Cyprus mention still yields the
    Cyprus-no-city segment.
    """
    if not text:
        return None
    patterns = _compiled_patterns(persona)
    grounded: set[str] = set()
    for segment, pattern in patterns["city_patterns"].items():
        for m in pattern.finditer(text):
            if _near_address_context(text, m.start(), m.end(), persona):
                grounded.add(segment)
                break
    if len(grounded) == 1:
        return next(iter(grounded))
    # 0 grounded cities (only incidental mentions) or an ambiguous multi-city office footprint:
    # do not guess a specific city. Downgrade to Cyprus-no-city when Cyprus is confirmed at all.
    if grounded or patterns["cyprus_pattern"].search(text):
        return (persona.geo_map_json or {}).get("cyprus_no_city_segment", "cyprus_other")
    return None


def _recipient_location_text(pers: dict[str, Any] | None) -> str:
    person_osint = (pers or {}).get("person_osint")
    if not isinstance(person_osint, dict):
        return ""
    return str(person_osint.get("recipient_location") or "").strip()


def _person_background_text(pers: dict[str, Any] | None) -> str:
    """Concatenated person_osint free-text fields — used only for the ex-CIS heuristic."""
    person_osint = (pers or {}).get("person_osint")
    if not isinstance(person_osint, dict):
        return ""
    parts = [
        str(person_osint.get(k) or "")
        for k in (
            "recipient_location",
            "career_summary",
            "recent_quotes_or_posts",
            "key_interests_or_focus_areas",
            "notable_achievements",
        )
    ]
    return " ".join(p for p in parts if p)


def _company_office_text(db: Session, contact: Contact) -> str:
    """Company office city/country text: company_evidence facts, then the raw osint_dossier."""
    if not contact.company:
        return ""
    from app.models.run_company import RunCompany

    rc = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == contact.run_id, RunCompany.name == contact.company)
        .first()
    )
    if not rc:
        return ""

    parts: list[str] = []
    try:
        from app.services.evidence_store import list_evidence_for_run_company

        for ev in list_evidence_for_run_company(db, rc.id):
            if ev.fact:
                parts.append(ev.fact)
    except Exception:
        pass
    try:
        from app.utils.run_company_extra import effective_run_company_extra

        kv = effective_run_company_extra(db, rc)
        dossier = kv.get("osint_dossier")
        if dossier:
            parts.append(str(dossier))
    except Exception:
        pass
    return " ".join(parts)


def resolve_geo_segment(
    db: Session, contact: Contact, persona: Any, pers: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve {segment: <persona segment key>, malindi: bool, ex_cis: bool} for this recipient.

    Never raises; unresolvable data defaults to persona.geo_map_json.default_segment,
    malindi=False.
    """
    geo_map = persona.geo_map_json or {}
    default_segment = geo_map.get("default_segment", "outside")
    try:
        segment = _segment_from_text(_recipient_location_text(pers), persona)
        if segment is None:
            # Company dossier is noisy free text (competitors, clients, closed offices, remote
            # history) — gate specific-city segments on address context (finding #5).
            segment = _segment_from_company_text(_company_office_text(db, contact), persona)
        if segment is None:
            segment = default_segment

        ex_cis_keywords = tuple(geo_map.get("ex_cis_keywords") or ())
        ex_cis = _text_has_any(_person_background_text(pers), ex_cis_keywords)

        # Conservative default (decision 3): no evidence of an ex-CIS background -> no Malindi.
        malindi_mod = (geo_map.get("modifiers") or {}).get("malindi") or {}
        applies_to = set(malindi_mod.get("applies_to_segments") or ())
        requires_ex_cis = malindi_mod.get("requires") == "ex_cis"
        malindi = segment in applies_to and (ex_cis if requires_ex_cis else True)

        return {"segment": segment, "malindi": malindi, "ex_cis": ex_cis}
    except Exception:
        return {"segment": default_segment, "malindi": False, "ex_cis": False}
