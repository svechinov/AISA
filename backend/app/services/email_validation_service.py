"""Heuristic validation for outbound drafts: personalization use, banned phrases, run-level dedup."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

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

    # --- AGENTIC CRITIC (Self-QA) ---
    from app.services.llm_gateway import complete_prompt_json_object, llm_configured
    if is_valid and llm_configured():
        try:
            facts = personalization.get('company_facts') or personalization.get('osint_dossier')
            critic_prompt = f"""
You are an elite B2B SDR Critic. Evaluate this cold email draft strictly on 3 criteria (1-5 scale).
Subject: {subject}
Body: {body}

Available evidence/facts: {facts}

Criteria:
1. relevance_score (1-5): How relevant is this to the company based on the facts? (1=generic, 5=highly tailored)
2. specificity_score (1-5): Does it use concrete facts/numbers/names from the evidence instead of fluff? (1=no facts, 5=hard evidence used)
3. non_spam_score (1-5): Does it avoid marketing jargon and sound like a personal 1-to-1 email? (1=spammy blast, 5=human and natural)

Return strict JSON:
{{
  "relevance_score": int,
  "specificity_score": int,
  "non_spam_score": int,
  "critique_issues": ["list of specific problems to fix, empty if all scores are 4+"]
}}
"""
            critic_json = complete_prompt_json_object(critic_prompt)
            total_critic = critic_json.get("relevance_score", 0) + critic_json.get("specificity_score", 0) + critic_json.get("non_spam_score", 0)
            
            logger.info("Email Critic scores: relevance=%s, specificity=%s, non_spam=%s (Total: %s/15)", 
                        critic_json.get("relevance_score"), critic_json.get("specificity_score"), 
                        critic_json.get("non_spam_score"), total_critic)

            # Require at least 12/15 total, and no single score < 3
            if total_critic < 12 or any(critic_json.get(k, 0) < 3 for k in ["relevance_score", "specificity_score", "non_spam_score"]):
                is_valid = False
                score -= 20
                for ci in critic_json.get("critique_issues", []):
                    issues.append({"code": "llm_critic_rejected", "detail": f"Critic Feedback: {ci}"})
                    logger.warning("Critic Rejected: %s", ci)
        except Exception as e:
            logger.warning("Critic evaluation failed: %s", e)

    return {
        "is_valid": is_valid,
        "issues": issues,
        "score": score,
        "peer_similarity_max": round(best_sim, 4),
    }
