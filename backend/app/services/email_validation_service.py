"""Heuristic validation for outbound drafts: personalization use, banned phrases, run-level dedup."""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

from app.services.critic_canon import DEFAULT_CRITIC_CANON
from app.services.hard_rules_gate import (
    ISSUE_CODE as HARD_RULE_ISSUE_CODE,
    check_hard_rules,
    company_name_from_personalization,
)
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

# --- Generation contract: email_kind (B-077, decision 1) ---
# The critic must judge each email against what the GENERATOR was told to produce, not against one
# universal "ideal cold email" ruler. `has_open_roles` in the pipeline (outreach_email_pipeline.py
# ~L443) already decides vacancy vs no-vacancy from the same vacancy_signals; email_kind carries
# that decision into the critic as an explicit argument, with a default derivation from
# personalization for callers that don't pass it (the email_drafts re-validate path, older tests).
EMAIL_KIND_VACANCY = "vacancy"
EMAIL_KIND_NO_VACANCY = "no_vacancy"

# no_vacancy §2.3 template-conformance (B-077, decision 2): the whole email is ~90% frozen verbatim
# (opener + who-we-are/when-you-open middle), so an LLM taste-rubric over it is noise about
# already-settled decisions and even fights the HARD RULE (Horns Up case). For no_vacancy we skip
# the rubric and instead mechanically confirm the §2.3 blocks are actually present, reusing the same
# fuzzy paragraph/sentence matching as _strip_fixed_blocks.
_NO_VACANCY_OPENER_MATCH = 0.6
_NO_VACANCY_MIDDLE_MATCH = 0.6


def _no_signal_template_enabled(persona: Any) -> bool:
    """True (current behavior) unless persona explicitly opts out. Treats a NULL column value —
    every pre-existing persona row before this toggle existed — the same as True, not as False."""
    if persona is None:
        return True
    value = getattr(persona, "no_signal_template_enabled", None)
    return True if value is None else bool(value)


def email_kind_for(personalization: dict[str, Any] | None, persona: Any = None) -> str:
    """Derive the generation contract from personalization — mirrors `has_open_roles` in the
    pipeline so the critic and the generator always agree on vacancy vs no-vacancy. Empty/absent
    vacancy_signals.open_roles normally ⇒ no_vacancy (the §2.3 template replaces the roles hook) —
    UNLESS the sending persona has no_signal_template_enabled=False: a persona with no frozen
    recruiting-industry fallback still gets a freely-authored letter, judged by the normal taste
    rubric, instead of being forced to reproduce AlexStaff's verbatim template."""
    vacancy_signals = (personalization or {}).get("vacancy_signals")
    has_open_roles = isinstance(vacancy_signals, dict) and bool(vacancy_signals.get("open_roles"))
    if has_open_roles:
        return EMAIL_KIND_VACANCY
    if not _no_signal_template_enabled(persona):
        return EMAIL_KIND_VACANCY
    return EMAIL_KIND_NO_VACANCY


_no_vacancy_variants_cache: list[tuple[list[str], list[str]]] | None = None


def _no_vacancy_template_variants() -> list[tuple[list[str], list[str]]]:
    """Per-language (openers, middle_paragraphs) — a conformant body reproduces ONE language's §2.3
    blocks (an EN email must not be required to also contain the RU middle). Cached at module level
    like _fixed_finale_blocks_cached: the templates are constants, so this is built once. Lazy
    import: outreach_email_pipeline imports this module, so a top-level import is circular."""
    global _no_vacancy_variants_cache
    if _no_vacancy_variants_cache is None:
        variants: list[tuple[list[str], list[str]]] = []
        try:
            from app.services.outreach_email_pipeline import (
                NO_VACANCY_MIDDLE,
                NO_VACANCY_OPENERS,
            )

            for lang, mid in NO_VACANCY_MIDDLE.items():
                openers = [t for t in NO_VACANCY_OPENERS.get(lang, {}).values() if t]
                variants.append((openers, _split_paragraphs(mid)))
        except Exception:  # noqa: BLE001 — never let a template-import problem break validation
            pass
        _no_vacancy_variants_cache = variants
    return _no_vacancy_variants_cache


def _check_no_vacancy_conformance(body: str) -> dict[str, str] | None:
    """Mechanical §2.3 conformance for no-vacancy emails: the body must reproduce one language's
    standing opener AND its who-we-are/when-you-open middle paragraphs (fuzzy match). Returns a
    fixable issue when the generator drifted off the verbatim template, else None."""
    variants = _no_vacancy_template_variants()
    if not variants:
        return None  # templates unavailable — don't manufacture a false reject

    paragraphs = _split_paragraphs(body)
    # The opener is matched against both paragraphs AND sentences: it is emitted as its own
    # paragraph (robust whole-block match), but paragraph-level also catches the case where the LLM
    # splits the opener across sentences — a sentence-only check would false-reject that and
    # wrongly resurrect the drift verdict on an otherwise-conformant email.
    opener_candidates = paragraphs + _split_sentences(body)

    for openers, middles in variants:
        opener_ok = not openers or any(
            _similarity_ratio(c, op) >= _NO_VACANCY_OPENER_MATCH
            for c in opener_candidates for op in openers
        )
        middles_ok = all(
            any(_similarity_ratio(p, mid) >= _NO_VACANCY_MIDDLE_MATCH for p in paragraphs)
            for mid in middles
        )
        if opener_ok and middles_ok:
            return None  # conforms fully to this language variant

    return {
        "code": "no_vacancy_template_drift",
        "detail": (
            "No-vacancy email must reproduce the §2.3 verbatim blocks (opener + "
            "who-we-are/when-you-open middle). Reproduce them exactly rather than improvising."
        ),
    }


# --- Fixed-block exclusion from peer-similarity (decision 4, B-063) ---
# The whole wave sharing the same closing paragraph (email_finale_templates) is a deliberate
# choice (decision 1), not something the critic should flag as duplication. The "We're
# AlexStaff..." opener sentence is likewise a standing block. Both are stripped from BOTH bodies
# before _text_similarity runs, via a fuzzy (not exact) match so the small synonym leeway allowed
# in the finale (happy<->glad, quick<->short) still gets recognized and stripped.
_OPENER_SENTENCES: tuple[str, ...] = (
    "We're AlexStaff — an IT-recruiting agency, recruiting for game studios and publishers since 2006.",
    "Мы — AlexStaff, IT-рекрутинговое агентство; подбираем для игровых студий и издателей с 2006 года.",
)

_fixed_finale_blocks: dict[Any, list[str]] = {}


def _fixed_finale_blocks_cached(persona: Any = None) -> list[str]:
    """Wave-identical paragraphs stripped before peer-similarity (decision 4): the persona's geo
    finale templates AND the no-vacancy opener + who-we-are/when-you-open paragraphs (finding #7 —
    the ~600-char no-vacancy block is deliberately shared across the wave and must not trip
    duplicate_peer). Cached per persona (B-071: different personas have different finales_json).
    persona=None falls back to the "alexey" persona (default_alexey_persona) so callers that
    haven't threaded a persona through yet (pure-function tests, older call sites) keep the old
    behavior. Imports are lazy: outreach_email_pipeline imports this module, so a top-level import
    would be circular."""
    if persona is None:
        from app.services.persona_service import default_alexey_persona

        persona = default_alexey_persona()
    cache_key = getattr(persona, "id", None) or getattr(persona, "slug", None) or id(persona)
    if cache_key not in _fixed_finale_blocks:
        from app.services.email_finale_templates import coerce_variant_list

        blocks: list[str] = []
        finales = persona.finales_json or {}
        for seg_data in (finales.get("segments") or {}).values():
            for raw in (seg_data.get("variants") or {}).values():
                # B-147: a variant slot can be a LIST of rotated options now, not just one string —
                # the critic must recognize ANY of a segment's variants as the known fixed block.
                blocks.extend(coerce_variant_list(raw))
        try:
            from app.services.outreach_email_pipeline import (
                NO_VACANCY_MIDDLE,
                NO_VACANCY_OPENERS,
            )

            for by_variant in NO_VACANCY_OPENERS.values():
                blocks.extend(t for t in by_variant.values() if t)
            for mid in NO_VACANCY_MIDDLE.values():
                # NO_VACANCY_MIDDLE is two paragraphs joined by a blank line; strip each on its own
                # so paragraph-level fuzzy matching (0.6) recognizes them.
                blocks.extend(_split_paragraphs(mid))
        except Exception:
            # Never let a no-vacancy-template import problem break core validation.
            pass
        _fixed_finale_blocks[cache_key] = blocks
    return _fixed_finale_blocks[cache_key]


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _similarity_ratio(a: str, b: str) -> float:
    # autojunk=False: difflib's default autojunk heuristic misfires on paragraph-length prose
    # (>200 chars) — it treats common characters as "popular"/junk and produces a badly-aligned,
    # much-too-low ratio for two paragraphs that only differ by a couple of synonym swaps.
    return difflib.SequenceMatcher(None, a.lower(), b.lower(), autojunk=False).ratio()


def _strip_fixed_blocks(text: str, persona: Any = None) -> str:
    """Drop known fixed blocks (finale templates, the 'We're AlexStaff...' opener sentence) from
    `text` before peer-similarity comparison. Whole paragraphs closely matching a finale template
    are dropped outright; sentences closely matching an opener are dropped from their paragraph."""
    finale_blocks = _fixed_finale_blocks_cached(persona)
    kept_paragraphs: list[str] = []
    for p in _split_paragraphs(text):
        if any(_similarity_ratio(p, fb) >= 0.6 for fb in finale_blocks):
            continue  # whole paragraph is a known closing block
        kept_sentences = [
            s for s in _split_sentences(p)
            if not any(_similarity_ratio(s, op) >= 0.7 for op in _OPENER_SENTENCES)
        ]
        if kept_sentences:
            kept_paragraphs.append(" ".join(kept_sentences))
    return "\n\n".join(kept_paragraphs)


# --- Named-role cross-check (decision 8, B-063) ---
# Mechanical, deterministic step: extract every job title named in the body (narrow LLM NER,
# cheap tier — no judgement, just extraction) and cross-check against vacancy_signals.open_roles.
# A named role with no match is an auto-reject — this catches the class of hallucination the
# LLM critic missed (19/20 of wave 3 passed with invented roles, see B-063 handoff).
ROLE_NER_SCHEMA = {"named_roles": ["string — each distinct job title/role mentioned in the email body"]}

_ROLE_FILLER_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "position", "role", "opening", "openings", "vacancy", "vacancies",
    "позиция", "позиции", "вакансия", "вакансии", "роль",
})

# Generic craft/seniority nouns that carry NO discipline-specific meaning on their own. They are
# dropped when deciding whether the email names a *specific* role (finding #1: the no-vacancy
# template legitimately says "engineer, artist, designer" / "инженер, художник, дизайнер" — those
# must NOT read as invented roles) and when matching a body role to a confirmed open role, so that
# the match keys on the distinctive token (unity/gameplay/match-3), not on shared filler. This
# fixes both the false-negative ("Senior Unreal Developer" ~ "Senior Unity Developer") and the
# false-positive ("Gameplay Programmer" vs "Gameplay Engineer") of the old 0.5-Jaccard rule (#3).
_GENERIC_ROLE_TOKENS: frozenset[str] = frozenset({
    "senior", "junior", "middle", "mid", "lead", "principal", "head", "chief", "staff",
    "engineer", "engineers", "developer", "developers", "programmer", "programmers", "dev",
    "artist", "artists", "designer", "designers", "manager", "managers", "analyst", "analysts",
    "producer", "producers", "director", "directors", "specialist", "specialists", "expert",
    "seat", "seats",
    "старший", "младший", "ведущий", "главный", "руководитель",
    "инженер", "инженеры", "разработчик", "разработчики", "программист", "программисты",
    "художник", "художники", "дизайнер", "дизайнеры", "менеджер", "аналитик", "продюсер",
    "специалист", "директор",
})


def _normalize_role_tokens(role: str) -> set[str]:
    r = (role or "").lower()
    r = re.sub(r"[^a-zа-яё0-9\s]", " ", r)
    return {t for t in r.split() if t and t not in _ROLE_FILLER_WORDS}


def _distinctive_role_tokens(role: str) -> set[str]:
    """Tokens that make a role SPECIFIC — everything left after filler and generic craft/seniority
    words are removed. Empty ⇒ the phrase is a bare craft category ('engineer'), not a concrete
    open-role claim."""
    return _normalize_role_tokens(role) - _GENERIC_ROLE_TOKENS


def _roles_match(named: str, open_roles: list[str]) -> bool:
    nd = _distinctive_role_tokens(named)
    if not nd:
        return True  # generic craft word, not a specific claim (also filtered upstream)
    for opened in open_roles:
        od = _distinctive_role_tokens(opened)
        # Match only when the distinctive tokens actually overlap AND one set contains the other:
        # 'unity' vs 'unreal' share nothing → reject (invented engine); 'gameplay engineer' vs
        # 'gameplay programmer' both reduce to {gameplay} → accept (synonym, not invented).
        if od and (nd & od) and (nd <= od or od <= nd):
            return True
    return False


def _extract_named_roles(body: str) -> list[str]:
    """Narrow LLM NER: every job title/role mentioned in the body. [] on any failure — the
    caller treats that as 'nothing to cross-check', never as a reason to reject."""
    from app.services.llm_gateway import complete_prompt_json_object
    from app.services.prompt_builder import build_prompt

    task = (
        "List every specific job title / role mentioned in this email body — e.g. 'Senior Unity "
        "Developer', '2D Artist', 'QA Engineer'. Do NOT include generic words like 'candidates', "
        "'team', 'staff'. Do NOT include the sender's own role (e.g. 'co-founder', 'recruiter' "
        "when it refers to AlexStaff). Empty list if none are named.\n\n"
        f"Email body:\n{body}"
    )
    prompt = build_prompt(task=task, data={}, rules=[], output_schema=ROLE_NER_SCHEMA)
    try:
        out = complete_prompt_json_object(prompt, task_kind="role_ner_extract")
    except Exception as e:
        logger.warning("Named-role extraction failed: %s", e)
        return []
    roles = out.get("named_roles") if isinstance(out, dict) else None
    if not isinstance(roles, list):
        return []
    return [str(r).strip() for r in roles if isinstance(r, str) and r.strip()]


def _check_named_roles(body: str, personalization: dict[str, Any]) -> dict[str, str] | None:
    """Returns an issue dict when the body names a role with no match in vacancy_signals.open_roles
    (or names one at all when vacancy_signals is empty), else None."""
    vacancy_signals = personalization.get("vacancy_signals")
    open_roles_raw: list[str] = []
    if isinstance(vacancy_signals, dict):
        open_roles_raw = [
            str(r.get("role") or "") for r in (vacancy_signals.get("open_roles") or [])
            if isinstance(r, dict) and (r.get("role") or "").strip()
        ]

    # Only *specific* roles are cross-checked. A bare craft category ('engineer', 'artist',
    # 'designer') carries no discipline claim and legitimately appears in the no-vacancy template
    # ("When you do open a seat — engineer, artist, designer"), so it must not read as invented
    # (finding #1). A role survives the filter only if it has a distinctive token (unity, match-3).
    named = [n for n in _extract_named_roles(body) if _distinctive_role_tokens(n)]
    if not named:
        return None

    if not open_roles_raw:
        return {
            "code": "invented_role",
            "detail": f"Body names specific role(s) {named!r} but vacancy_signals is empty — no confirmed open roles for this recipient.",
        }

    unmatched = [n for n in named if not _roles_match(n, open_roles_raw)]
    if unmatched:
        return {
            "code": "invented_role",
            "detail": f"Body names role(s) {unmatched!r} not found among confirmed open_roles {open_roles_raw!r}.",
        }
    return None


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


def _ev_str(ev: Any) -> str | None:
    return str(ev) if ev else None


def _run_taste_rubric(
    subject: str,
    body: str,
    company_ev: Any,
    person_ev: Any,
    vacancy_ev: Any,
    critic_canon: str | None,
) -> dict[str, Any] | None:
    """Прогон LLM-рубрики вкуса (B-077 etap 2). Чистый вкус, без механических проверок.
    Возвращает dict {scores, total, hook_grounded, hook_fail, taste_pass, critique_issues}
    или None, если LLM не сконфигурирован. Тот же промпт-скелет, что был inline —
    используется и regression-прогонщиком (замороженный evidence + текущий канон)."""
    from app.services.llm_gateway import complete_prompt_json_object, llm_configured

    if not llm_configured():
        return None

    has_evidence = bool(company_ev or person_ev or vacancy_ev)
    canon = (critic_canon or "").strip() or DEFAULT_CRITIC_CANON
    critic_prompt = f"""{canon}

Subject: {subject}
Body: {body}

Company evidence/facts: {company_ev}
Person evidence (person_osint, may be empty): {person_ev}
Vacancy signals (open roles confirmed by research, may be empty): {vacancy_ev}

Return strict JSON:
{{
  "relevance_score": int, "specificity_score": int, "non_spam_score": int,
  "cta_score": int, "clarity_score": int,
  "hook_grounded": true,
  "critique_issues": ["specific problems to fix; empty if all good"]
}}
"""
    cj = complete_prompt_json_object(critic_prompt, task_kind="email_critic")
    scores = {k: int(cj.get(k, 0) or 0) for k in CRITIC_RUBRIC_KEYS}
    total = sum(scores.values())
    hook_ok = bool(cj.get("hook_grounded", True))
    logger.info("Email Critic rubric: %s total=%s/25 hook_grounded=%s", scores, total, hook_ok)

    below_floor = any(v < CRITIC_MIN_PER_CRITERION for v in scores.values())
    hook_fail = has_evidence and not hook_ok
    taste_pass = not (total < CRITIC_MIN_TOTAL or below_floor or hook_fail)
    return {
        "scores": scores,
        "total": total,
        "hook_grounded": hook_ok,
        "hook_fail": hook_fail,
        "taste_pass": taste_pass,
        "critique_issues": cj.get("critique_issues", []),
    }


def validate_outbound_email(
    subject: str,
    body: str,
    personalization: dict[str, Any],
    peer_bodies: list[str],
    email_kind: str | None = None,
    critic_canon: str | None = None,
    persona: Any = None,
    expected_finale_variants: list[str] | None = None,
    company_name: str | None = None,
    max_authored_words: int | None = None,
) -> dict[str, Any]:
    """
    Returns { is_valid, issues, score }.
    issues: list of { code, detail }.

    email_kind (B-077): the generation contract — "vacancy" or "no_vacancy". When None it is derived
    from personalization (email_kind_for). no_vacancy skips the LLM taste-rubric and validates §2.3
    template conformance mechanically instead (decision 2); the honesty gates run for both kinds.

    critic_canon (B-077 etap 2): the editable taste-rubric text injected into the vacancy critic
    prompt (see app.services.critic_canon). Empty/None falls back to DEFAULT_CRITIC_CANON so the
    vacancy critic behaves exactly as before for callers that don't pass a per-run canon yet.

    persona (B-071): the sending persona, whose finales_json drives the fixed-block peer-similarity
    exclusion (decision 4, B-063). None falls back to the "alexey" persona (see
    _fixed_finale_blocks_cached) so callers that don't pass a run's persona yet keep old behavior.

    expected_finale_variants (B-158): the exact verbatim closing-paragraph options valid for this
    recipient's resolved segment (email_finale_templates.get_finale_variants). The body is now
    assembled by appending one of these in code (never written by the LLM) — this is a mechanical
    byte-gate, defense-in-depth against any path that still lets the model write its own closing:
    if given and non-empty, the body MUST end with one of them exactly, or this is a critical fail
    (finale_verbatim_mismatch), same severity as invented_role. None/empty skips the gate (callers
    that haven't threaded a persona/segment through yet keep old behavior).

    company_name (B-273): the recipient company, used by the deterministic HARD RULES gate (subject
    must name it, the 24-72h promise must name it). None falls back to the "Named organization: X."
    fact in personalization; when neither is available the company-dependent rules are skipped
    rather than guessed.

    max_authored_words (Фаза 2, Task 1): потолок HARD RULE 4 для этой кампании
    (run_context_service.get_max_authored_words). None = канонные 180 слов и их дословная
    формулировка — вызывающие, которые поле не прокидывают, сохраняют прежнее поведение.
    """
    if email_kind is None:
        email_kind = email_kind_for(personalization, persona)
    is_no_vacancy = email_kind == EMAIL_KIND_NO_VACANCY

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

    role_issue = _check_named_roles(bod, personalization)
    if role_issue:
        issues.append(role_issue)
        score -= 40

    # B-158: hard byte-gate — the body must end with one of the segment's exact verbatim closing
    # variants. The generator no longer writes its own closing (it's appended in code), so this
    # should always pass in normal operation; it exists to catch the model rewriting/dropping the
    # closing anyway (e.g. the incident that motivated B-158: a self-written "continue over email"
    # closing with an em dash, when the real variant was appended nowhere in the body).
    if expected_finale_variants:
        normalized_variants = [v.strip() for v in expected_finale_variants if v and v.strip()]
        if normalized_variants and not any(bod.endswith(v) for v in normalized_variants):
            issues.append(
                {
                    "code": "finale_verbatim_mismatch",
                    "detail": "Body does not end with one of the expected verbatim closing-paragraph variants for this segment (B-158).",
                },
            )
            score -= 40

    # B-273: deterministic HARD RULES gate, BEFORE the LLM critic. The taste rubric scores content,
    # not canon compliance — four drafts with 2-4 violations each scored 100/100 on 29.07. Rules
    # with a literal shape (attributes of the posting in the subject/hook, em dash, sign-off, the
    # 24-72h promise without the company, who-we-are out of the second paragraph) are checked here
    # mechanically; the verbatim blocks appended in code are excluded from the check.
    hard_rule_issues = check_hard_rules(
        subject or "",
        bod,
        company_name=(company_name or "").strip() or company_name_from_personalization(personalization),
        fixed_blocks=_fixed_finale_blocks_cached(persona),
        check_structure=not is_no_vacancy,
        max_authored_words=max_authored_words,
    )
    for hr_issue in hard_rule_issues:
        issues.append(hr_issue)
    if hard_rule_issues:
        score -= 30

    # no_vacancy honesty gate (B-077, decision 2/4): the §2.3 verbatim blocks must be present. This
    # replaces the LLM taste-rubric for this kind — the body is frozen canon, so conformance is a
    # mechanical check, not a matter of taste. Fixable by regeneration (the generator drifted).
    if is_no_vacancy:
        conformance_issue = _check_no_vacancy_conformance(bod)
        if conformance_issue:
            issues.append(conformance_issue)
            score -= 40

    # Fixed blocks (finale, "We're AlexStaff..." opener) are deliberately identical across the
    # wave (decision 1/4, B-063) — strip them from BOTH bodies before comparing so the shared
    # closing paragraph doesn't trip duplicate_peer.
    stripped_bod = _strip_fixed_blocks(bod, persona)
    best_sim = 0.0
    for peer in peer_bodies or []:
        peer_t = (peer or "").strip()
        if not peer_t:
            continue
        sim = _text_similarity(stripped_bod, _strip_fixed_blocks(peer_t, persona))
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
        i["code"] in (
            "banned_phrase", "duplicate_peer", "invented_role", "no_vacancy_template_drift",
            "finale_verbatim_mismatch", HARD_RULE_ISSUE_CODE,
        )
        for i in issues
    )
    is_valid = score >= 55 and not critical

    # --- AGENTIC CRITIC (Self-QA, rubric-based) ---
    # Rubric scoring (5 criteria) + hook-grounding check. Bounded: the caller retries at most
    # MAX_VALIDATION_RETRIES times, so this cannot loop indefinitely (cost control).
    # B-077 (decision 2): skipped entirely for no_vacancy — the body is ~90% frozen §2.3 verbatim,
    # so an LLM taste-judgement is noise about settled decisions and even fights the HARD RULE
    # (Horns Up case). no_vacancy honesty is fully covered by the mechanical checks above.
    # B-077 etap 2: the taste-rubric outcome (scores/hook/canon/evidence) is persisted separately
    # from is_valid/issues so the calibration matrix can compare taste vs Alex, not mechanics vs Alex.
    taste: dict[str, Any] | None = None
    critic_canon_used: str | None = None
    critic_evidence: dict[str, Any] | None = None
    if is_valid and not is_no_vacancy:
        try:
            company_ev = personalization.get("company_facts") or personalization.get("osint_dossier")
            person_ev = personalization.get("person_osint")
            vacancy_ev = personalization.get("vacancy_signals")
            taste = _run_taste_rubric(subject, body, company_ev, person_ev, vacancy_ev, critic_canon)
            if taste is not None:
                critic_canon_used = (critic_canon or "").strip() or DEFAULT_CRITIC_CANON
                critic_evidence = {
                    "company_ev": _ev_str(company_ev),
                    "person_ev": _ev_str(person_ev),
                    "vacancy_ev": _ev_str(vacancy_ev),
                }
                if not taste["taste_pass"]:
                    is_valid = False
                    score -= 20
                    if taste["hook_fail"]:
                        issues.append({
                            "code": "hook_not_grounded",
                            "detail": "Open with a concrete fact/trigger from the evidence (person if available, else company) — not a generic opener.",
                        })
                        logger.warning("Critic: hook not grounded in evidence")
                    for ci in taste["critique_issues"]:
                        issues.append({"code": "llm_critic_rejected", "detail": f"Critic Feedback: {ci}"})
                        logger.warning("Critic Rejected: %s", ci)
        except Exception as e:
            logger.warning("Critic evaluation failed: %s", e)
            taste = None

    return {
        "is_valid": is_valid,
        "issues": issues,
        "score": score,
        "peer_similarity_max": round(best_sim, 4),
        "critic_taste_pass": (taste["taste_pass"] if taste else None),
        "critic_scores": (taste["scores"] if taste else None),
        "critic_hook_grounded": (taste["hook_grounded"] if taste else None),
        "critic_canon_used": critic_canon_used,
        "critic_evidence": critic_evidence,
    }
