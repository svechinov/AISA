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

# --- LLM critic rubric (Self-QA). Tunable; later movable to run_setup for per-campaign control. ---
CRITIC_RUBRIC_KEYS = (
    "relevance_score",
    "specificity_score",
    "non_spam_score",
    "cta_score",
    "clarity_score",
)
CRITIC_MIN_PER_CRITERION = 3  # any single criterion below this → reject
CRITIC_MIN_TOTAL = 20  # out of len(CRITIC_RUBRIC_KEYS) * 5 = 25


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

    # --- AGENTIC CRITIC (Self-QA, rubric-based) ---
    # Rubric scoring (5 criteria) + hook-grounding check. Bounded: the caller retries at most
    # MAX_VALIDATION_RETRIES times, so this cannot loop indefinitely (cost control).
    from app.services.llm_gateway import complete_prompt_json_object, llm_configured
    if is_valid and llm_configured():
        try:
            company_ev = personalization.get("company_facts") or personalization.get("osint_dossier")
            person_ev = personalization.get("person_osint")
            has_evidence = bool(company_ev or person_ev)
            critic_prompt = f"""
You are an elite B2B SDR Critic. Score this cold email on a strict rubric (each 1-5).
Subject: {subject}
Body: {body}

Company evidence/facts: {company_ev}
Person evidence (person_osint, may be empty): {person_ev}

Criteria (1=poor, 5=excellent):
1. relevance_score: fit to THIS company based on the evidence (1=generic, 5=highly tailored).
2. specificity_score: uses concrete facts/names from the evidence, not fluff (1=no facts, 5=hard evidence used).
3. non_spam_score: human 1-to-1 tone, no marketing jargon (1=spammy blast, 5=natural).
4. cta_score: ONE clear low-friction CTA (short call), not vague or multiple (1=weak/none, 5=crisp).
5. clarity_score: clear, concise, well-structured, appropriate length (1=rambling, 5=tight).

Also judge:
hook_grounded (true/false): does the OPENING reference a concrete fact/trigger from the evidence
(prefer person_osint when present, else company evidence)? false if the opener is generic.

Return strict JSON:
{{
  "relevance_score": int, "specificity_score": int, "non_spam_score": int,
  "cta_score": int, "clarity_score": int,
  "hook_grounded": true,
  "critique_issues": ["specific problems to fix; empty if all good"]
}}
"""
            cj = complete_prompt_json_object(critic_prompt)
            scores = {k: int(cj.get(k, 0) or 0) for k in CRITIC_RUBRIC_KEYS}
            total = sum(scores.values())
            hook_ok = bool(cj.get("hook_grounded", True))
            logger.info("Email Critic rubric: %s total=%s/25 hook_grounded=%s", scores, total, hook_ok)

            below_floor = any(v < CRITIC_MIN_PER_CRITERION for v in scores.values())
            hook_fail = has_evidence and not hook_ok
            if total < CRITIC_MIN_TOTAL or below_floor or hook_fail:
                is_valid = False
                score -= 20
                if hook_fail:
                    issues.append({
                        "code": "hook_not_grounded",
                        "detail": "Open with a concrete fact/trigger from the evidence (person if available, else company) — not a generic opener.",
                    })
                    logger.warning("Critic: hook not grounded in evidence")
                for ci in cj.get("critique_issues", []):
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
