"""Resolve outbound email voice: run.email_style_mode (professional profile) + role heuristics when Auto."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.utils.contact_source_payload import effective_contact_source_json

# Stored on runs.email_style_mode (slug). "auto" = infer from contact role.
VALID_PROFESSIONAL_PROFILES = frozenset(
    {
        "auto",
        "any_top_management",
        "founder_or_ceo",
        "cto_or_developer",
        "cmo_or_marketing",
        "head_of_licensing",
        "cfo_or_accountants",
        "vp_or_other_dm",
        "any_c_level",
        "any_mid_management",
    },
)

# Legacy UI stored direct/warm/sharp/executive — treat as Auto.
LEGACY_EMAIL_VOICE_MODES = frozenset({"direct", "warm", "sharp", "executive"})

# LLM style buckets used in prompts (STYLE_INSTRUCTIONS).
VALID_EMAIL_STYLE_MODES = frozenset({"direct", "warm", "sharp", "executive"})

STYLE_INSTRUCTIONS: dict[str, str] = {
    "direct": "Voice: short sentences, explicit ask, minimal throat-clearing.",
    "warm": "Voice: friendly and conversational while staying professional.",
    "sharp": "Voice: crisp, confident, specific; avoid hedging and filler.",
    "executive": "Voice: concise, outcome-oriented, respectful of the reader’s time.",
}

_PROFILE_TO_STYLE: dict[str, str] = {
    "auto": "direct",
    "any_top_management": "executive",
    "founder_or_ceo": "direct",
    "cto_or_developer": "direct",
    "cmo_or_marketing": "warm",
    "head_of_licensing": "executive",
    "cfo_or_accountants": "executive",
    "vp_or_other_dm": "executive",
    "any_c_level": "executive",
    "any_mid_management": "warm",
}


def normalize_email_style_mode(raw: str | None) -> str | None:
    """Return canonical slug for DB, or None. Maps legacy voice modes to auto."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in LEGACY_EMAIL_VOICE_MODES:
        return "auto"
    if s in VALID_PROFESSIONAL_PROFILES:
        return s
    raise ValueError(
        "Invalid email_style_mode; use a profile slug such as founder_or_ceo, any_top_management, or auto.",
    )


def _role_lower(db: Session, contact: Any) -> str:
    r = (getattr(contact, "role", None) or "").strip().lower()
    if r:
        return r
    sj = effective_contact_source_json(db, contact) if getattr(contact, "id", None) else {}
    if not sj:
        sj = getattr(contact, "source_json", None) or {}
    if isinstance(sj, dict):
        for k in ("role", "title", "job_title", "position"):
            v = sj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return ""


def _infer_style_from_role(role_lower: str) -> str | None:
    if not role_lower:
        return None
    if re.search(r"\b(founder|co-?founder|ceo|cto|cfo|owner)\b", role_lower):
        return "direct"
    if re.search(r"\b(marketing|growth|brand|content|cmo)\b", role_lower):
        return "warm"
    if re.search(r"\b(partnership|partner|bizdev|business development|alliances)\b", role_lower):
        return "executive"
    if re.search(r"\b(vp|vice president|head of|director)\b", role_lower):
        return "executive"
    return None


def resolve_effective_email_style(db: Session, run: Any, contact: Any) -> str:
    """
    Priority when run.email_style_mode is a specific profile: profile → style.
    When auto / legacy / empty: role heuristic → direct.
    """
    raw = getattr(run, "email_style_mode", None)
    if isinstance(raw, str) and raw.strip():
        m = raw.strip().lower()
        if m in LEGACY_EMAIL_VOICE_MODES:
            m = "auto"
        if m in VALID_PROFESSIONAL_PROFILES and m != "auto":
            st = _PROFILE_TO_STYLE.get(m, "direct")
            if st in VALID_EMAIL_STYLE_MODES:
                return st
    inferred = _infer_style_from_role(_role_lower(db, contact))
    if inferred:
        return inferred
    return "direct"


def style_prompt_fragment(style_mode: str) -> str:
    """Short paragraph for LLM prompts."""
    s = (style_mode or "direct").strip().lower()
    if s not in VALID_EMAIL_STYLE_MODES:
        s = "direct"
    return STYLE_INSTRUCTIONS.get(s, STYLE_INSTRUCTIONS["direct"])
