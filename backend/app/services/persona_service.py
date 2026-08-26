"""Persona resolution for the outreach engine (B-071 stage A): identity — self-intro, verbatim
finales, geo-segment keyword tables, signature — is read from the run's persona, never from a
hardcoded sender. Empty run.persona_id resolves to the "alexey" persona (decision 8, current
single-tenant default).

This module also holds the "alexey" persona's canonical data — the byte-identical migration of
the old FINALE_TEMPLATES/SEGMENT_NAMES (email_finale_templates.py) and the Cyprus keyword tables
(geo_segment_service.py). It lives here, in app/ (shipped in the Docker image), rather than in
backend/scripts/seed_alexstaff_preset.py: per AI-Biz-OS/CLAUDE.md "Грабли", scripts/ is NOT baked
into the prod image, so code that needs this data at runtime (default_alexey_persona() below, used
whenever a caller hasn't threaded a persona through yet) must not depend on it. The seed script
imports alexey_persona_kwargs() from here to upsert the DB row (see seed_alexstaff_preset.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.models.persona import Persona

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.run import Run

ALEXEY_SLUG = "alexey"
STEPAN_SLUG = "stepan"
ANASTASIA_SLUG = "anastasia"

# --- Geo-map (B-063 constants, migrated verbatim from geo_segment_service.py) ---

_CYPRUS_KEYWORDS: tuple[str, ...] = ("cyprus", "кипр", "кипре", "кипра", "kypros")

_CITY_SEGMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "paphos": ("paphos", "пафос", "пафосе", "пафоса"),
    "limassol": ("limassol", "лимасол", "лимассол", "лимасоле", "лимассоле"),
    "larnaca_nicosia": (
        "larnaca", "ларнак", "ларнака", "ларнаке",
        "nicosia", "никоси", "никосия", "никосии",
    ),
}

_EX_CIS_KEYWORDS: tuple[str, ...] = (
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

_ADDRESS_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "office", "based", "headquarter", "hq", "located", "situated", "address", "registered",
    "офис", "штаб", "находится", "располож", "базирует", "адрес", "зарегистр", "прописк",
)

_NEGATION_CONTEXT_KEYWORDS: tuple[str, ...] = (
    "closed", "former", "formerly", "shut", "no longer", "used to", "ex-", "previously",
    "закрыл", "закрыт", "бывш", "ранее", "больше не", "покин",
)

ALEXEY_GEO_MAP_JSON: dict[str, Any] = {
    "default_segment": "outside",
    "cyprus_no_city_segment": "cyprus_other",
    "cyprus_keywords": list(_CYPRUS_KEYWORDS),
    "city_segments": {seg: list(kws) for seg, kws in _CITY_SEGMENT_KEYWORDS.items()},
    "ex_cis_keywords": list(_EX_CIS_KEYWORDS),
    "address_context_keywords": list(_ADDRESS_CONTEXT_KEYWORDS),
    "negation_context_keywords": list(_NEGATION_CONTEXT_KEYWORDS),
    "modifiers": {
        # Old: malindi = segment in (2, 3, 4) and ex_cis -> limassol/larnaca_nicosia/cyprus_other.
        "malindi": {
            "applies_to_segments": ["limassol", "larnaca_nicosia", "cyprus_other"],
            "requires": "ex_cis",
        },
        # Old: segment 4 without Malindi collapses into segment 3's no-Malindi verbatim variant.
        "segment4_collapse": {"from": "cyprus_other", "to_no_malindi_of": "larnaca_nicosia"},
    },
}

# --- Finales (B-063 constants, migrated verbatim from email_finale_templates.py) ---

ALEXEY_FINALES_JSON: dict[str, Any] = {
    "segments": {
        "paphos": {
            "label": "Paphos",
            "prompt_ordinal": 1,
            "variants": {
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
        },
        "limassol": {
            "label": "Limassol",
            "prompt_ordinal": 2,
            "variants": {
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
        },
        "larnaca_nicosia": {
            "label": "Larnaca/Nicosia",
            "prompt_ordinal": 3,
            "variants": {
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
        },
        "cyprus_other": {
            "label": "Cyprus, city unknown",
            "prompt_ordinal": 4,
            "variants": {
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
        },
        "outside": {
            "label": "outside Cyprus",
            "prompt_ordinal": 5,
            "variants": {
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
        },
    },
    # Decision 10, B-071: explicit fallback chain — chins the latent defect where segment 5 (RU)
    # silently got the EN text. Old get_finale_text special-cased segment 5 to ignore `language`
    # entirely and pick only between "en"/"en_ex_cis"; this fallback + the generic resolver in
    # email_finale_templates.py reproduce that exact behavior without the special case.
    "fallbacks": {
        "outside.ru": "outside.en",
    },
}

ALEXEY_SIGNATURE_HTML = (
    "<p>Alexey<br>"
    "AlexStaff Agency — recruiting for game studios and publishers since 2006<br>"
    '<a href="mailto:alex@alexstaff.agency">alex@alexstaff.agency</a> · '
    '<a href="https://alexstaff.agency">alexstaff.agency</a><br>'
    "Based in Cyprus</p>"
)


def alexey_persona_kwargs() -> dict[str, Any]:
    """Persona field values for the "alexey" row — used by seed_alexstaff_preset.py to upsert the
    DB row and by default_alexey_persona() to build an in-memory fallback."""
    return {
        "slug": ALEXEY_SLUG,
        "display_name": "Alexey",
        "self_intro": None,  # verbatim self-intro lives inside finales_json, not here
        "signature_html": ALEXEY_SIGNATURE_HTML,
        "timezone": "Asia/Nicosia",
        "languages_json": ["Russian", "English"],
        "geo_map_json": ALEXEY_GEO_MAP_JSON,
        "finales_json": ALEXEY_FINALES_JSON,
        "proof_anchors_json": None,
        "primary_mailbox_email": "alex@alexstaff.agency",
    }


# --- Stepan persona (B-071 final stage: US COO, decision 11-15а, multitenancy-personas-handoff-
# 2026-07-18.md). Texts below are Алексей's verbatim-approved wording (18.07) — seed byte-for-byte,
# do not touch. Unlike alexey, this persona has no in-memory runtime fallback: it is an ordinary DB
# row referenced via runs.persona_id, not the single-tenant default. ---

STEPAN_GEO_MAP_JSON: dict[str, Any] = {
    "default_segment": "us",
    "cyprus_no_city_segment": None,
    "cyprus_keywords": [],
    "city_segments": {},
    "ex_cis_keywords": list(_EX_CIS_KEYWORDS),
    "address_context_keywords": [],
    "negation_context_keywords": [],
    "modifiers": {},
}

STEPAN_FINALES_JSON: dict[str, Any] = {
    "segments": {
        "us": {
            "label": "United States",
            "prompt_ordinal": 1,
            "variants": {
                "en": (
                    "I'm the agency's COO and I'm based here in the States, so a call is easy to "
                    "fit into your schedule. Happy to grab 15 minutes to get acquainted and talk "
                    "through how we might help with your hiring — or we can just as easily keep it "
                    "to email, whichever works better. What would suit you?"
                ),
                "en_ex_cis": (
                    "I'm the agency's COO and I'm based here in the States, so a call is easy to "
                    "fit into your schedule. Happy to grab 15 minutes to get acquainted and talk "
                    "through how we might help with your hiring — or we can just as easily continue "
                    "here or on Telegram, whichever works better. What would suit you?"
                ),
            },
        },
    },
    "fallbacks": {},
}

# CAN-SPAM (B-128 Phase 1a): US-track signature must carry a physical postal address and a
# working opt-out. The address is not known yet, so the block below carries a placeholder token
# substituted at render time from settings.CAN_SPAM_POSTAL_ADDRESS (see run_context_service.
# get_sender_signature_html); sending_gates blocks send while the setting is empty (Phase 1c).
# Opt-out is reply-based ("reply STOP"), not a link — decision 19.07, natural fit for personal
# B2B email; reply_classifier.py routes it to the "unsubscribe" label and suppresses the contact.
CAN_SPAM_ADDRESS_PLACEHOLDER = "{{CAN_SPAM_POSTAL_ADDRESS}}"

STEPAN_SIGNATURE_HTML = (
    "<p>Stepan Pakhanov<br>"
    "COO, AlexStaff Agency — recruiting for game studios and publishers since 2006<br>"
    '<a href="mailto:stepan@alexstaff.agency">stepan@alexstaff.agency</a> · '
    '<a href="https://alexstaff.agency">alexstaff.agency</a><br>'
    "Based in the US</p>"
    f"<p>{CAN_SPAM_ADDRESS_PLACEHOLDER}<br>"
    "If you'd rather not hear from us, just reply \"STOP\" and I'll take you off my list.</p>"
)


def stepan_persona_kwargs() -> dict[str, Any]:
    """Persona field values for the "stepan" row — used by seed_alexstaff_preset.py to upsert the
    DB row. Self-intro (COO) lives inside the finale text itself, not in self_intro."""
    return {
        "slug": STEPAN_SLUG,
        "display_name": "Stepan Pakhanov",
        "self_intro": None,
        "signature_html": STEPAN_SIGNATURE_HTML,
        "timezone": "America/New_York",
        "languages_json": ["English"],
        "geo_map_json": STEPAN_GEO_MAP_JSON,
        "finales_json": STEPAN_FINALES_JSON,
        "proof_anchors_json": None,
        "primary_mailbox_email": "stepan@alexstaff.agency",
    }


# --- Anastasia persona (B-533): account manager, sends RU and EN out of the same run. Not seeded
# into any RunSetup canon here — the live run (id=5) was hand-created in prod and only its
# signature is synced (see seed_alexstaff_preset.py --fields). SIGNATURE_CLOSING_PLACEHOLDER (the
# "{{CLOSING}}" token, outbound_email_body.py) picks the sign-off greeting per drafted body
# language; SIGNATURE_LOGO_CID ("asa-logo") is the inline logo shipped in backend/app/assets/. ---

ANASTASIA_SIGNATURE_HTML = (
    "{{CLOSING}}<br>"
    "Anastasiya Zemlyanskaya<br>"
    "Account Manager, Alex Staff Agency<br>"
    '<a href="mailto:account-manager@alexstaff.agency">account-manager@alexstaff.agency</a><br>'
    '<a href="https://t.me/Ana_Zem_AlexStaff">Telegram: @Ana_Zem_AlexStaff</a>'
    '<div style="margin-top:10px;"><img src="cid:asa-logo" width="180" alt="Alex Staff Agency" '
    'style="display:block;width:180px;height:auto;border:0;"></div>'
)


def anastasia_persona_kwargs() -> dict[str, Any]:
    """Persona field values for the "anastasia" row — used by seed_alexstaff_preset.py to upsert
    the DB row."""
    return {
        "slug": ANASTASIA_SLUG,
        "display_name": "Anastasiya Zemlyanskaya",
        "self_intro": (
            "Account manager at Alex Staff Agency; ведёт коммуникации с существующими и бывшими "
            "клиентами агентства."
        ),
        "signature_html": ANASTASIA_SIGNATURE_HTML,
        "timezone": "Asia/Nicosia",
        "languages_json": ["ru", "en"],
        "geo_map_json": None,
        "finales_json": None,
        "proof_anchors_json": None,
        "primary_mailbox_email": "account-manager@alexstaff.agency",
    }


_default_alexey_persona: Persona | None = None


def default_alexey_persona() -> Persona:
    """In-memory (non-persisted) "alexey" Persona — the fallback identity for callers that have no
    DB session or haven't threaded a persona through yet (e.g. pure-function unit tests). Not a new
    "our sender" singleton: it's the same alexey data get_run_persona() resolves to when persona_id
    is empty (decision 8), just without requiring the DB round-trip."""
    global _default_alexey_persona
    if _default_alexey_persona is None:
        _default_alexey_persona = Persona(**alexey_persona_kwargs())
    return _default_alexey_persona


def get_run_persona(db: "Session", run: "Run | None") -> Persona:
    """Resolve the sending persona for a run: run.persona_id -> Persona row; empty/missing ->
    the "alexey" persona (decision 8, current single-tenant default)."""
    persona_id = getattr(run, "persona_id", None)
    if persona_id:
        persona = db.get(Persona, persona_id)
        if persona:
            return persona
    persona = db.query(Persona).filter(Persona.slug == ALEXEY_SLUG).first()
    if persona:
        return persona
    return default_alexey_persona()
