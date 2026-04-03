"""Heuristic validation for outbound drafts: personalization use, banned phrases, run-level dedup."""

from __future__ import annotations

import re
from typing import Any

from app.services.outreach_personalize import normalize_text_for_dedup

# Case-insensitive substring bans (generic outreach fluff).
BANNED_PHRASES: tuple[str, ...] = (
    "i came across your company",
    "we help companies like yours",
    "i wanted to reach out",
    "hope you're doing well",
    "i hope this email finds you well",
    "i hope this finds you well",
    "just following up",
    "touching base",
)

# Jaccard similarity on normalized word sets above this → duplicate vs peer.
PEER_SIMILARITY_THRESHOLD = 0.88


def _text_similarity(a: str, b: str) -> float:
    na = normalize_text_for_dedup(a)
    nb = normalize_text_for_dedup(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    sa = set(na.split())
    sb = set(nb.split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def _banned_hits(body: str) -> list[str]:
    bl = (body or "").lower()
    out: list[str] = []
    for phrase in BANNED_PHRASES:
        if phrase in bl:
            out.append(phrase)
    return out


def _fact_appears_in_body(fact: str, body: str) -> bool:
    if not fact or not body:
        return False
    bl = body.lower()
    for w in re.findall(r"[a-z0-9]{4,}", fact.lower()):
        if len(w) > 12:
            continue
        if w in bl:
            return True
    return False


def _why_reflected(why: str, body: str) -> bool:
    if not why or len(why) < 20:
        return True
    bl = body.lower()
    snippet = why.strip().lower()[:120]
    words = [w for w in re.findall(r"[a-z]{5,}", snippet) if len(w) < 20]
    hits = sum(1 for w in words[:8] if w in bl)
    return hits >= 1


def validate_outbound_email(
    subject: str,
    body: str,
    personalization: dict[str, Any],
    peer_bodies: list[str],
) -> dict[str, Any]:
    """
    Returns { is_valid, issues, score }.
    issues: list of { code, detail }.
    """
    issues: list[dict[str, str]] = []
    score = 100

    bod = (body or "").strip()

    for phrase in _banned_hits(bod):
        issues.append({"code": "banned_phrase", "detail": f"Banned phrase: {phrase!r}"})
        score -= 28

    facts = personalization.get("company_facts") or []
    if isinstance(facts, list) and facts:
        used = any(_fact_appears_in_body(str(f), bod) for f in facts if f)
        if not used:
            issues.append(
                {
                    "code": "company_fact_not_used",
                    "detail": "Body does not clearly reflect any company_facts (when facts were provided).",
                },
            )
            score -= 22

    why = (personalization.get("why_this_company") or "").strip()
    if why and not _why_reflected(why, bod):
        issues.append(
            {
                "code": "why_weak",
                "detail": "Strengthen tie to why_this_company / reason for this recipient.",
            },
        )
        score -= 12

    best_sim = 0.0
    for peer in peer_bodies or []:
        peer_t = (peer or "").strip()
        if not peer_t:
            continue
        sim = _text_similarity(bod, peer_t)
        if sim > best_sim:
            best_sim = sim
        if sim >= PEER_SIMILARITY_THRESHOLD:
            issues.append(
                {
                    "code": "duplicate_peer",
                    "detail": f"Too similar to another draft in this run (similarity ~{sim:.2f}).",
                },
            )
            score -= 35
            break

    score = max(0, min(100, score))

    critical = any(
        i["code"] in ("banned_phrase", "duplicate_peer") for i in issues
    )
    is_valid = score >= 55 and not critical

    return {
        "is_valid": is_valid,
        "issues": issues,
        "score": score,
        "peer_similarity_max": round(best_sim, 4),
    }
