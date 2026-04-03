"""Resolve outbound email voice: run.email_style_mode + role heuristics."""

from __future__ import annotations

import re
from typing import Any

VALID_EMAIL_STYLE_MODES = frozenset({"direct", "warm", "sharp", "executive"})

STYLE_INSTRUCTIONS: dict[str, str] = {
    "direct": "Voice: short sentences, explicit ask, minimal throat-clearing.",
    "warm": "Voice: friendly and conversational while staying professional.",
    "sharp": "Voice: crisp, confident, specific; avoid hedging and filler.",
    "executive": "Voice: concise, outcome-oriented, respectful of the reader’s time.",
}


def _role_lower(contact: Any) -> str:
    r = (getattr(contact, "role", None) or "").strip().lower()
    if r:
        return r
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


def resolve_effective_email_style(run: Any, contact: Any) -> str:
    """
    Priority: role heuristic → run.email_style_mode → 'direct'.
    """
    inferred = _infer_style_from_role(_role_lower(contact))
    if inferred:
        return inferred
    raw = getattr(run, "email_style_mode", None)
    if isinstance(raw, str) and raw.strip().lower() in VALID_EMAIL_STYLE_MODES:
        return raw.strip().lower()
    return "direct"


def style_prompt_fragment(style_mode: str) -> str:
    """Short paragraph for LLM prompts."""
    s = (style_mode or "direct").strip().lower()
    if s not in VALID_EMAIL_STYLE_MODES:
        s = "direct"
    return STYLE_INSTRUCTIONS.get(s, STYLE_INSTRUCTIONS["direct"])
