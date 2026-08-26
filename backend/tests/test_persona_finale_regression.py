"""B-071 stage A regression harness (Definition of Done — hard invariant): migrating Alexey's
identity out of hardcoded FINALE_TEMPLATES/SEGMENT_NAMES (email_finale_templates.py) and Cyprus
keyword constants (geo_segment_service.py) into persona data must not change a single byte of what
reaches the LLM prompt or the generated finale text.

This file freezes the OLD (pre-B-071) implementation as local `_legacy_*` functions/constants —
copied verbatim from the modules before the migration — and asserts they agree with the NEW
persona-driven resolvers on the "alexey" persona, built from the same canonical data
(app.services.persona_service.alexey_persona_kwargs, also used by
scripts/seed_alexstaff_preset.py to seed the DB row). Do not "fix" anything in the _legacy_*
block below — it is the byte-identity baseline the new code must reproduce.

2026-07-21 exception (Alexey's approved wording change, canon iteration #2): "I'm in Limassol
most weeks" -> "I'm often in Limassol" in all 5 EN variant-A finale texts below and in
persona_service.py, kept in lockstep so this stays a real byte-identity check against the
CURRENT approved wording, not a stale one.
"""

from __future__ import annotations

import importlib
import pkgutil
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.persona import Persona
from app.services.email_finale_templates import finale_instruction_block
from app.services.geo_segment_service import resolve_geo_segment
from app.services.persona_service import alexey_persona_kwargs

# Register every model with Base BEFORE any ORM instance (e.g. Persona(...) below) is constructed
# — SQLAlchemy configures ALL mappers in the shared registry on first use, and a relationship
# (e.g. Contact -> ContactPersonalization) fails to resolve if its target class was never
# imported yet. Same pattern as test_geo_segment_service.py's `session` fixture.
import app.models as _models_pkg  # noqa: E402

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

# ---------------------------------------------------------------------------------------------
# Frozen legacy email_finale_templates.py (pre-B-071)
# ---------------------------------------------------------------------------------------------

_LEGACY_SEGMENT_NAMES: dict[int, str] = {
    1: "Paphos",
    2: "Limassol",
    3: "Larnaca/Nicosia",
    4: "Cyprus, city unknown",
    5: "outside Cyprus",
}

_LEGACY_FINALE_TEMPLATES: dict[int, dict[str, str]] = {
    1: {
        "ru": (
            "Я кофаундер агентства, живу в Пафосе — можем встретиться за чашкой кофе и "
            "познакомиться, а заодно обсудить возможное сотрудничество. Ну или просто "
            "созвонимся на 15 минут. Как вам удобнее?"
        ),
        "en": (
            "I co-founded the agency and live here in Paphos — happy to meet over a coffee, get "
            "acquainted and talk through how we might help with your hiring. Or we could simply "
            "hop on a 15-minute call — whichever is easier. Would some day this or next week "
            "work?"
        ),
    },
    2: {
        "ru": (
            "Я кофаундер агентства; живу в Пафосе, но часто бываю в Лимасоле — могу заехать на "
            "чашку кофе: познакомимся поближе и обсудим возможное сотрудничество; а ещё можно "
            "пересечься в любую среду на iT_Party в Malindi. Ну или просто созвонимся на 15 "
            "минут. Как вам удобнее?"
        ),
        "en": (
            "I co-founded the agency; I live in Paphos but I'm often in Limassol — I'd "
            "gladly drop by for a coffee to get acquainted and talk through how we might work "
            "together, or we could catch each other any Wednesday at the iT_Party at "
            "Malindi. Or simply a 15-minute call. What works best for you?"
        ),
        "ru_no_malindi": (
            "Я кофаундер агентства; живу в Пафосе, но часто бываю в Лимасоле — могу заехать на "
            "чашку кофе: познакомимся поближе и обсудим возможное сотрудничество. Ну или просто "
            "созвонимся на 15 минут. Как вам удобнее?"
        ),
        "en_no_malindi": (
            "I co-founded the agency; I live in Paphos but I'm often in Limassol — I'd "
            "gladly drop by for a coffee to get acquainted and talk through how we might work "
            "together. Or simply a 15-minute call. What works best for you?"
        ),
    },
    3: {
        "ru": (
            "Я кофаундер агентства; живу в Пафосе, но часто бываю в Лимасоле — если тоже там "
            "бываете, можем встретиться за чашкой кофе, познакомиться поближе и обсудить "
            "возможное сотрудничество; а если заглядываете по средам на iT_Party в Malindi "
            "— можем пересечься там. Ну или просто созвонимся на 15 минут. Как вам удобнее?"
        ),
        "en": (
            "I co-founded the agency; I live in Paphos and I'm often in Limassol — if "
            "you're ever around, let's grab a coffee, get acquainted and talk through how we "
            "might work together; and if you ever drop by the Wednesday iT_Party at "
            "Malindi, we could meet there. Or simply a 15-minute call. What would be easiest?"
        ),
        "ru_no_malindi": (
            "Я кофаундер агентства; живу в Пафосе, но часто бываю в Лимасоле — если тоже там "
            "бываете, можем встретиться за чашкой кофе, познакомиться поближе и обсудить "
            "возможное сотрудничество. Ну или просто созвонимся на 15 минут. Как вам удобнее?"
        ),
        "en_no_malindi": (
            "I co-founded the agency; I live in Paphos and I'm often in Limassol — if "
            "you're ever around, let's grab a coffee, get acquainted and talk through how we "
            "might work together. Or simply a 15-minute call. What would be easiest?"
        ),
    },
    4: {
        "ru": (
            "Я кофаундер агентства; живу в Пафосе, но часто бываю в Лимасоле — проще всего "
            "пересечься в любую среду на iT_Party в Malindi: познакомимся поближе и обсудим "
            "возможное сотрудничество. Ну или просто созвонимся на 15 минут. Как вам удобнее?"
        ),
        "en": (
            "I co-founded the agency; I live in Paphos and I'm often in Limassol — the "
            "easiest might be to catch each other any Wednesday at the iT_Party at "
            "Malindi, get acquainted and talk through how we might work together. Or simply a "
            "15-minute call. What works better for you?"
        ),
    },
    5: {
        "en": (
            "I co-founded the agency — I'm based in Cyprus myself. Happy to jump on a quick "
            "15-minute call, or we can just as easily continue over email, whichever is easier. "
            "What would suit you?"
        ),
        "en_ex_cis": (
            "I co-founded the agency — I'm based in Cyprus myself. Happy to jump on a quick "
            "15-minute call, or we can just as easily continue here or on Telegram, whichever is "
            "easier. What would suit you?"
        ),
    },
}


def _legacy_get_finale_text(
    segment: int, language: str, ex_cis: bool = False, malindi: bool = True
) -> str:
    block = _LEGACY_FINALE_TEMPLATES.get(segment) or _LEGACY_FINALE_TEMPLATES[5]
    if segment == 5:
        return block["en_ex_cis"] if ex_cis else block["en"]
    lang_key = "ru" if (language or "").strip().lower() == "russian" else "en"
    if not malindi and segment in (2, 3):
        no_malindi_key = f"{lang_key}_no_malindi"
        if no_malindi_key in block:
            return block[no_malindi_key]
    return block.get(lang_key) or block.get("en") or ""


def _legacy_finale_instruction_block(segment: int, language: str, malindi: bool, ex_cis: bool) -> str:
    effective_segment = 3 if (segment == 4 and not malindi) else segment
    text = _legacy_get_finale_text(effective_segment, language, ex_cis, malindi)
    name = _LEGACY_SEGMENT_NAMES.get(effective_segment, "")
    return (
        f"CLOSING PARAGRAPH (segment {effective_segment}/{name}) — USE THIS VERBATIM as the "
        "email's final paragraph (self-intro + meeting offer + one closing CTA question). Only "
        "synonym-level leeway is allowed (e.g. 'happy to' <-> 'glad to', 'quick' <-> 'short'); "
        "do not restructure the sentence or change its meaning:\n"
        f'"{text}"'
    )


# Old int segment -> new persona segment key (decision 8, B-071 handoff).
_SEGMENT_KEY_BY_INT = {
    1: "paphos", 2: "limassol", 3: "larnaca_nicosia", 4: "cyprus_other", 5: "outside",
}


# ---------------------------------------------------------------------------------------------
# Frozen legacy geo_segment_service.py (pre-B-071)
# ---------------------------------------------------------------------------------------------

_LEGACY_CYPRUS_KEYWORDS: tuple[str, ...] = ("cyprus", "кипр", "кипре", "кипра", "kypros")

_LEGACY_CITY_SEGMENT_KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("paphos", "пафос", "пафосе", "пафоса"),
    2: ("limassol", "лимасол", "лимассол", "лимасоле", "лимассоле"),
    3: (
        "larnaca", "ларнак", "ларнака", "ларнаке",
        "nicosia", "никоси", "никосия", "никосии",
    ),
}

_LEGACY_EX_CIS_KEYWORDS: tuple[str, ...] = (
    "russia", "russian", "moscow", "petersburg", "рф", "снг", "россия", "россии", "москва",
    "ukraine", "ukrainian", "kyiv", "kiev", "украина", "украин", "киев",
    "belarus", "minsk", "беларус", "минск",
    "kazakhstan", "almaty", "казахстан", "алматы",
    "armenia", "yerevan", "армения", "ереван",
    "georgia", "tbilisi", "грузия", "тбилиси",
    "azerbaijan", "baku", "азербайджан", "баку",
    "uzbekistan", "tashkent", "узбекистан", "ташкент",
    "ex-ussr", "ex-cis", "post-soviet", "постсоветск",
)

_LEGACY_ADDRESS_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "office", "based", "headquarter", "hq", "located", "situated", "address", "registered",
    "офис", "штаб", "находится", "располож", "базирует", "адрес", "зарегистр", "прописк",
)

_LEGACY_NEGATION_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "closed", "former", "formerly", "shut", "no longer", "used to", "ex-", "previously",
    "закрыл", "закрыт", "бывш", "ранее", "больше не", "покин",
)

_LEGACY_ADDRESS_CONTEXT_WINDOW = 60


def _legacy_boundary_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(sorted((re.escape(k) for k in keywords), key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + alts + r")", re.IGNORECASE | re.UNICODE)


_LEGACY_CITY_PATTERNS = {
    seg: _legacy_boundary_pattern(kws) for seg, kws in _LEGACY_CITY_SEGMENT_KEYWORDS.items()
}
_LEGACY_CYPRUS_PATTERN = _legacy_boundary_pattern(_LEGACY_CYPRUS_KEYWORDS)
_LEGACY_ADDRESS_CONTEXT_PATTERN = _legacy_boundary_pattern(_LEGACY_ADDRESS_CONTEXT_KEYWORDS)
_LEGACY_NEGATION_CONTEXT_PATTERN = _legacy_boundary_pattern(_LEGACY_NEGATION_CONTEXT_KEYWORDS)


def _legacy_text_has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return bool(_legacy_boundary_pattern(keywords).search(text or ""))


def _legacy_segment_from_text(text: str) -> int | None:
    if not text:
        return None
    for segment, pattern in _LEGACY_CITY_PATTERNS.items():
        if pattern.search(text):
            return segment
    if _LEGACY_CYPRUS_PATTERN.search(text):
        return 4
    return None


def _legacy_near_address_context(text: str, start: int, end: int) -> bool:
    lo = max(0, start - _LEGACY_ADDRESS_CONTEXT_WINDOW)
    hi = min(len(text), end + _LEGACY_ADDRESS_CONTEXT_WINDOW)
    window = text[lo:hi]
    if _LEGACY_NEGATION_CONTEXT_PATTERN.search(window):
        return False
    return bool(_LEGACY_ADDRESS_CONTEXT_PATTERN.search(window))


def _legacy_segment_from_company_text(text: str) -> int | None:
    if not text:
        return None
    grounded: set[int] = set()
    for segment, pattern in _LEGACY_CITY_PATTERNS.items():
        for m in pattern.finditer(text):
            if _legacy_near_address_context(text, m.start(), m.end()):
                grounded.add(segment)
                break
    if len(grounded) == 1:
        return next(iter(grounded))
    if grounded or _LEGACY_CYPRUS_PATTERN.search(text):
        return 4
    return None


def _legacy_recipient_location_text(pers) -> str:
    person_osint = (pers or {}).get("person_osint")
    if not isinstance(person_osint, dict):
        return ""
    return str(person_osint.get("recipient_location") or "").strip()


def _legacy_person_background_text(pers) -> str:
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


def _legacy_company_office_text(db, contact) -> str:
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


def _legacy_resolve_geo_segment(db, contact, pers=None) -> dict:
    try:
        segment = _legacy_segment_from_text(_legacy_recipient_location_text(pers))
        if segment is None:
            segment = _legacy_segment_from_company_text(_legacy_company_office_text(db, contact))
        if segment is None:
            segment = 5

        ex_cis = _legacy_text_has_any(_legacy_person_background_text(pers), _LEGACY_EX_CIS_KEYWORDS)
        malindi = segment in (2, 3, 4) and ex_cis

        return {"segment": segment, "malindi": malindi, "ex_cis": ex_cis}
    except Exception:
        return {"segment": 5, "malindi": False, "ex_cis": False}


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def persona_alexey() -> Persona:
    """The "alexey" persona built from the exact data seed_alexstaff_preset.py upserts (via
    app.services.persona_service.alexey_persona_kwargs) — an in-memory, non-persisted row."""
    return Persona(**alexey_persona_kwargs())


@pytest.fixture()
def geo_session(tmp_path):
    import app.models as models_pkg
    from app.db import Base

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")

    engine = create_engine(f"sqlite:///{(tmp_path / 'geo_regress.db').as_posix()}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_contact(session, *, company: str = "Acme"):
    from app.models.contact import Contact
    from app.models.project import Project
    from app.models.run import Run

    project = Project(name="geo-regress", type="generic")
    session.add(project)
    session.commit()
    run = Run(project_id=project.id, workflow_name="generic_outreach", name="geo-regress-run")
    session.add(run)
    session.commit()
    contact = Contact(run_id=run.id, company=company, email="x@acme.com", name="Jo", role="CEO")
    session.add(contact)
    session.commit()
    return contact


# ---------------------------------------------------------------------------------------------
# A9.2 — finale_instruction_block: all combinations of segment x language x ex_cis x malindi
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("segment_int", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("language", ["Russian", "English"])
@pytest.mark.parametrize("ex_cis", [True, False])
@pytest.mark.parametrize("malindi", [True, False])
def test_finale_instruction_block_byte_identical(persona_alexey, segment_int, language, ex_cis, malindi):
    legacy = _legacy_finale_instruction_block(segment_int, language, malindi, ex_cis)
    new = finale_instruction_block(
        persona_alexey, _SEGMENT_KEY_BY_INT[segment_int], language, malindi, ex_cis
    )
    assert new == legacy


# ---------------------------------------------------------------------------------------------
# A9.3 — resolve_geo_segment: recipient_location + company-dossier corpus (test_geo_segment_
# service.py's scenarios), old int-segment resolver vs new persona-driven resolver.
# ---------------------------------------------------------------------------------------------

_GEO_CORPUS_SIMPLE: list[tuple[str, dict]] = [
    ("paphos_own_location", {"person_osint": {"recipient_location": "Paphos, Cyprus"}}),
    ("limassol_own_location", {"person_osint": {"recipient_location": "Limassol"}}),
    ("larnaca_own_location", {"person_osint": {"recipient_location": "Larnaca"}}),
    ("nicosia_own_location", {"person_osint": {"recipient_location": "Nicosia"}}),
    ("cyprus_no_city", {"person_osint": {"recipient_location": "Cyprus"}}),
    ("no_data_anywhere", {}),
    (
        "ex_cis_background_enables_malindi",
        {
            "person_osint": {
                "recipient_location": "Limassol",
                "career_summary": "Previously led engineering at a Moscow-based studio.",
            }
        },
    ),
    (
        "no_ex_cis_evidence_keeps_malindi_off",
        {
            "person_osint": {
                "recipient_location": "Limassol",
                "career_summary": "Led product at a Berlin studio.",
            }
        },
    ),
    (
        "segment_5_never_gets_malindi_even_with_ex_cis",
        {
            "person_osint": {
                "recipient_location": "Belgrade",
                "career_summary": "Moscow, Russia born and raised.",
            }
        },
    ),
    ("malformed_personalization", {"person_osint": "not-a-dict"}),
]


@pytest.mark.parametrize("case_name,pers", _GEO_CORPUS_SIMPLE)
def test_resolve_geo_segment_byte_identical_simple(geo_session, persona_alexey, case_name, pers):
    contact = _make_contact(geo_session)
    legacy = _legacy_resolve_geo_segment(geo_session, contact, pers)
    new = resolve_geo_segment(geo_session, contact, persona_alexey, pers)
    assert new["segment"] == _SEGMENT_KEY_BY_INT[legacy["segment"]]
    assert new["malindi"] == legacy["malindi"]
    assert new["ex_cis"] == legacy["ex_cis"]


def test_resolve_geo_segment_byte_identical_company_office_city(geo_session, persona_alexey):
    """No recipient_location -> company_evidence facts (city text) resolve the segment."""
    from app.models.company_evidence import CompanyEvidence
    from app.models.run_company import RunCompany

    contact = _make_contact(geo_session, company="Nekki")
    rc = RunCompany(run_id=contact.run_id, collect_index=1, name="Nekki", website="nekki.com")
    geo_session.add(rc)
    geo_session.commit()
    geo_session.add(
        CompanyEvidence(
            run_company_id=rc.id, run_id=contact.run_id, kind="evidence",
            fact="Office address: Kimonos 43A, Limassol, Cyprus",
        )
    )
    geo_session.commit()

    legacy = _legacy_resolve_geo_segment(geo_session, contact, {})
    new = resolve_geo_segment(geo_session, contact, persona_alexey, {})
    assert new["segment"] == _SEGMENT_KEY_BY_INT[legacy["segment"]]
    assert new["malindi"] == legacy["malindi"]
    assert new["ex_cis"] == legacy["ex_cis"]


def test_resolve_geo_segment_byte_identical_osint_dossier_country(geo_session, persona_alexey):
    """No recipient_location, no evidence rows -> osint_dossier KV text (country-only mention)."""
    from app.models.run_company import RunCompany
    from app.utils.run_company_extra import persist_run_company_extra

    contact = _make_contact(geo_session, company="Playnetic")
    rc = RunCompany(run_id=contact.run_id, collect_index=1, name="Playnetic", website="playnetic.com")
    geo_session.add(rc)
    geo_session.commit()
    persist_run_company_extra(
        geo_session, rc,
        {"osint_dossier": '{"evidence": [{"fact": "Headquartered in Valletta, Malta"}]}'},
    )
    geo_session.commit()

    legacy = _legacy_resolve_geo_segment(geo_session, contact, {})
    new = resolve_geo_segment(geo_session, contact, persona_alexey, {})
    assert new["segment"] == _SEGMENT_KEY_BY_INT[legacy["segment"]]
    assert new["malindi"] == legacy["malindi"]
    assert new["ex_cis"] == legacy["ex_cis"]


def test_resolve_geo_segment_byte_identical_ambiguous_offices(geo_session, persona_alexey):
    """Two conflicting office cities in address context -> Cyprus-no-city, not a guess."""
    from app.models.company_evidence import CompanyEvidence
    from app.models.run_company import RunCompany

    contact = _make_contact(geo_session, company="Multi")
    rc = RunCompany(run_id=contact.run_id, collect_index=1, name="Multi", website="multi.com")
    geo_session.add(rc)
    geo_session.commit()
    geo_session.add(
        CompanyEvidence(
            run_company_id=rc.id, run_id=contact.run_id, kind="evidence",
            fact="Offices in Paphos and Limassol",
        )
    )
    geo_session.commit()

    legacy = _legacy_resolve_geo_segment(geo_session, contact, {})
    new = resolve_geo_segment(geo_session, contact, persona_alexey, {})
    assert new["segment"] == _SEGMENT_KEY_BY_INT[legacy["segment"]]
    assert new["malindi"] == legacy["malindi"]
    assert new["ex_cis"] == legacy["ex_cis"]
