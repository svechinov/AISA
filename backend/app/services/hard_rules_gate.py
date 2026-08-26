"""Deterministic HARD RULES gate (B-273) — mechanical canon conformance, checked before the LLM critic.

The 29.07 add-on wave (drafts 91-94) passed the critic 100/100 with `hook_grounded` ✓ while every
one of the four letters broke 2-4 HARD RULES: vacancy attributes recited back at the recipient in
the subject and the hook ("four Irvine roles", "both fully remote across the US and Canada" — HARD
RULE 8), the 24-72h promise without the company name (HARD RULE 1), and a who-we-are block that had
slipped out of the second paragraph so the letter never said who we are until the signature.

The LLM rubric cannot catch these: its five criteria score CONTENT (relevance, specificity, tone,
CTA, clarity), not rule compliance. Rules with a literal shape belong in regexes, not in another
prompt — cheaper, deterministic, and impossible to talk out of. This module holds exactly those:
each check maps to a numbered HARD RULE of the canon (backend/scripts/seed_alexstaff_preset.py,
`PROMPT_SETUP_TEXT`). Taste stays with the critic.

Deliberately NOT checked here: R-015...R-017 (retention wording, `art direction`, the 24-72 formula
phrasing) — those calibration rules are not in the canon yet, and a gate must never enforce a rule
the generator was never given.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

ISSUE_CODE = "hard_rule_violation"

# Generic corporate words that carry no company identity — same idea as the vacancy radar's
# slug guard: "Games"/"Studio" in a subject line does not mean the company was named.
_GENERIC_COMPANY_TOKENS: frozenset[str] = frozenset({
    "games", "game", "studio", "studios", "interactive", "entertainment", "digital", "media",
    "software", "tech", "technologies", "labs", "lab", "group", "team", "the", "ltd", "limited",
    "inc", "llc", "gmbh", "co", "company", "productions", "production",
})

# --- HARD RULE 8: never recite the posting's attributes back at the recipient -------------------
# Checked in the subject and in the hook paragraph only: the rule explicitly allows an attribute
# LATER in the body when it carries our offer ("remote or multi-country roles -> we source
# worldwide"), so the whole body must not be swept.
_HR8_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:fully\s+|100%\s+|full[-\s]?time\s+|part[-\s]?time\s+)?(?:remote|hybrid|on[-\s]?site|in[-\s]?office)\b",
                   re.IGNORECASE),
        "work-format attribute (remote/hybrid/on-site)",
    ),
    (
        re.compile(r"\b(?:senior|junior|mid[-\s]?level|middle|principal|entry[-\s]?level)\b", re.IGNORECASE),
        "seniority grade of the posting",
    ),
    (
        re.compile(r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+(?:[A-Za-z][\w-]+\s+)?"
                   r"(?:roles?|positions?|openings?|vacanc(?:y|ies)|seats?)\b", re.IGNORECASE),
        "role count / location of the postings",
    ),
    (
        re.compile(r"\b(?:roles?|positions?|openings?|vacanc(?:y|ies))\s+(?:in|across|throughout|based\s+in)\s+\w",
                   re.IGNORECASE),
        "location of the postings",
    ),
    (
        re.compile(r"\bacross\s+(?:the\s+)?(?:US|U\.S\.|USA|EU|UK|Canada|Europe)\b"),
        "geography of the postings",
    ),
)

# --- HARD RULE 9: no sign-off / valediction (the signature block is appended by the system) -----
_SIGN_OFF_RE = re.compile(
    r"^(?:best(?:\s+regards)?|regards|kind\s+regards|sincerely|cheers|thanks(?:\s+again)?|"
    r"thank\s+you|warmly|talk\s+soon|yours(?:\s+truly)?|с\s+уважением)\b[\s,.!]*$",
    re.IGNORECASE,
)

# --- HARD RULE 15: no em dash in what the model writes (verbatim blocks are exempt) -------------
_EM_DASH_CHARS: tuple[str, ...] = ("—", "–")

# --- HARD RULE 1: the 24-72h promise names the company --------------------------------------
_PROMISE_RE = re.compile(r"\b24\s*(?:-|–|—|to|до)\s*72\b|\b24-72\b", re.IGNORECASE)

# --- Structure (HARD RULE 4 + gold-standard): who-we-are is the SECOND authored paragraph -------
_WHO_WE_ARE_RE = re.compile(r"(?:we[''`]?re|we\s+are)\s+alexstaff|мы\s*[—-]?\s*alexstaff", re.IGNORECASE)

# Salutation line ("Hi Serge,") is not a content paragraph.
_SALUTATION_RE = re.compile(r"^(?:hi|hello|hey|dear|привет|здравствуйте)\b[^.!?]{0,40}[,:]?$", re.IGNORECASE)

# HARD RULE 4: ~120-140 words in the authored part. Only a generous upper bound is enforced — the
# gate must catch the essay, not argue about a 145-word letter.
_MAX_AUTHORED_WORDS = 180


def _issue(rule: str, detail: str) -> dict[str, str]:
    return {"code": ISSUE_CODE, "detail": f"HARD RULE {rule}: {detail}"}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9а-яё]+", (text or "").lower())


def company_name_tokens(company_name: str | None) -> list[str]:
    """Identifying tokens of the company name (generic corporate words dropped). Empty when the
    name is entirely generic — then a "was the company named?" check is not decidable."""
    return [t for t in _tokens(company_name or "") if t not in _GENERIC_COMPANY_TOKENS and len(t) >= 3]


def mentions_company(text: str, company_name: str | None) -> bool | None:
    """Does `text` name the company? None when undecidable (no name / all-generic name)."""
    toks = company_name_tokens(company_name)
    if not toks:
        return None
    hay = " ".join(_tokens(text))
    compact_hay = re.sub(r"\s+", "", hay)
    if any(t in hay.split() for t in toks):
        return True
    # "SecondDinner" written solid, or a name spelled with punctuation inside.
    return "".join(toks) in compact_hay


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def authored_paragraphs(body: str, fixed_blocks: list[str] | None = None) -> list[str]:
    """Paragraphs the MODEL wrote: the appended verbatim closing (and any other known fixed block)
    is dropped, the salutation line is dropped. Fuzzy match at the same 0.6 ratio the peer-similarity
    stripper uses, so a finale variant is recognized even with its allowed synonym leeway."""
    blocks = [b for b in (fixed_blocks or []) if b and b.strip()]
    out: list[str] = []
    for p in split_paragraphs(body):
        if any(difflib.SequenceMatcher(None, p.lower(), b.lower(), autojunk=False).ratio() >= 0.6 for b in blocks):
            continue
        if _SALUTATION_RE.match(p):
            continue
        out.append(p)
    return out


def _check_subject_names_company(subject: str, company_name: str | None) -> list[dict[str, str]]:
    named = mentions_company(subject, company_name)
    if named is False:
        return [_issue("6", f"the subject line must include the company name ({company_name!r}): {subject!r}")]
    return []


def _check_vacancy_attributes(subject: str, hook: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for where, text in (("subject", subject), ("hook paragraph", hook)):
        for pattern, what in _HR8_PATTERNS:
            m = pattern.search(text or "")
            if m:
                issues.append(
                    _issue(
                        "8",
                        f"do not recite the posting's attributes back at the recipient — "
                        f"{what} in the {where}: {m.group(0).strip()!r}. Name the role plainly.",
                    )
                )
    return issues


def _check_sign_off(paragraphs: list[str]) -> list[dict[str, str]]:
    if not paragraphs:
        return []
    lines = [ln.strip() for ln in paragraphs[-1].splitlines() if ln.strip()]
    for ln in lines[-2:]:
        if _SIGN_OFF_RE.match(ln):
            return [_issue("9", f"no sign-off or valediction in the body — the signature is appended automatically: {ln!r}")]
    return []


def _check_em_dash(paragraphs: list[str]) -> list[dict[str, str]]:
    for p in paragraphs:
        for ch in _EM_DASH_CHARS:
            if ch in p:
                return [_issue("15", f"no em dash in the body you write — use a hyphen or split the sentence (found {ch!r})")]
    return []


def _check_promise_names_company(paragraphs: list[str], company_name: str | None) -> list[dict[str, str]]:
    for p in paragraphs:
        if not _PROMISE_RE.search(p):
            continue
        if mentions_company(p, company_name) is False:
            return [
                _issue(
                    "1",
                    "the 24-72 hour promise must name the company the candidate wants to join "
                    f"({company_name!r}) — speed alone is not the promise.",
                )
            ]
        return []
    return []


def _check_structure(paragraphs: list[str]) -> list[dict[str, str]]:
    idx = next((i for i, p in enumerate(paragraphs) if _WHO_WE_ARE_RE.search(p)), None)
    if idx is None or idx == 1:
        return []
    return [
        _issue(
            "4",
            f"the who-we-are block (\"We're AlexStaff - ...\") belongs in the SECOND paragraph, "
            f"right after the hook — it is currently paragraph {idx + 1}.",
        )
    ]


def _check_length(paragraphs: list[str]) -> list[dict[str, str]]:
    words = sum(len(p.split()) for p in paragraphs)
    if words > _MAX_AUTHORED_WORDS:
        return [_issue("4", f"the body you write is about 120-140 words in 3 short paragraphs — this one has {words}.")]
    return []


def check_hard_rules(
    subject: str,
    body: str,
    *,
    company_name: str | None = None,
    fixed_blocks: list[str] | None = None,
    check_structure: bool = True,
) -> list[dict[str, str]]:
    """Every HARD RULE violation found in this draft, as validation issues (empty list = clean).

    `fixed_blocks` are the verbatim blocks appended in code (finale variants, no-vacancy template) —
    they are exempt from the rules that govern what the MODEL writes (HARD RULE 15 says so
    explicitly) and are excluded before the authored text is checked.

    `check_structure=False` for no-vacancy letters: their shape is the frozen §2.3 template, already
    validated mechanically by _check_no_vacancy_conformance.
    """
    paragraphs = authored_paragraphs(body, fixed_blocks)
    hook = paragraphs[0] if paragraphs else ""

    issues: list[dict[str, str]] = []
    issues += _check_subject_names_company(subject or "", company_name)
    issues += _check_vacancy_attributes(subject or "", hook)
    issues += _check_sign_off(paragraphs)
    issues += _check_em_dash(paragraphs)
    if check_structure:
        issues += _check_promise_names_company(paragraphs, company_name)
        issues += _check_structure(paragraphs)
        issues += _check_length(paragraphs)
    return issues


def company_name_from_personalization(personalization: dict[str, Any] | None) -> str | None:
    """Recover the recipient company from personalization when the caller did not pass it: the
    facts block always opens with "Named organization: <company>." (personalization_service)."""
    facts = (personalization or {}).get("company_facts")
    if not isinstance(facts, list):
        return None
    for f in facts:
        m = re.match(r"\s*Named organization:\s*(.+?)\.?\s*$", str(f or ""))
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None
