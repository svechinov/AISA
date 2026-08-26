"""Vacancy radar (v1): detect that a company is actively hiring — the strongest outreach
trigger for a recruiting agency ("you are hiring X right now; our first candidate arrives
in 24-72h").

Pure functions with no run/DB dependency so a scheduled watchlist radar (phase 2) can reuse
them unchanged. v1 is called per company from osint_worker.enrich_crm_data and persisted in
run_company_extra KV as `vacancy_signals`.

Source cascade (B-062, learned from the 2026-07-15 live web-check — see the B-062/B-063
handoff): general web search alone missed every company in wave 3. Targeted sources first,
with an early exit on the first source that yields usable evidence:
(a) the company's own careers page (derived from company.website: /careers /jobs /career
    /vacancies), fetched directly (trafilatura -> Tavily fallback via
    company_source_extractor._extract_page_text) — the most reliable source when it exists;
(b) known ATS platforms by company-name slug: Ashby's public job-board JSON API (clean,
    no LLM guesswork needed to see the roles), Greenhouse, Huntflow, Pinpoint — any of these
    may simply not respond for a given company, which is fine, we move on;
(c) LinkedIn Jobs via search_web snippets;
(d) the original general web search (last resort, same behaviour as v1.0).

Cost profile: at most one direct-fetch chain (a+b) plus up to a handful of search_web calls
(c, d) + 1 LLM extraction per company. Returns None when no hiring evidence is found anywhere
or extraction fails — callers must NOT persist None (retry-friendly, same rule as the OSINT
dossier).

B-265 (US wave 1, 29.07): the company's OWN careers page outranks everything else in the cascade
in BOTH directions. Before it only outranked them positively (a page with roles wins); a page that
explicitly says "we have no positions open" was ignored and the weaker stages below then invented
a hiring signal out of a blog post or a LinkedIn artifact (Supergiant: site says no openings, radar
reported two engineering roles from the blog + Facebook). Two rules now:
  - an own careers page declaring "no open positions" ends the cascade with a NEGATIVE verdict
    (`declared_no_openings`), which the caller persists — no roles, no further sources;
  - a hiring post in a blog / social network / news feed is not evidence of an open role, so those
    URLs are dropped from the weak stages (c, d) entirely.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

EXTRACTION_SCHEMA = {
    "is_hiring": "boolean — true only when the evidence shows CURRENT open roles",
    "open_roles": [
        {
            "role": "string",
            "seniority": "string or empty",
            "location": "string or empty — city of the role, if visible in the evidence",
            "country": "string or empty — country of the role, if visible in the evidence",
            "evidence_url": "string",
        }
    ],
    "summary": "string: one line, e.g. 'Hiring: senior Unity dev, 2D artist (careers page, LinkedIn)'",
}

_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

CAREERS_PATHS: tuple[str, ...] = ("careers", "jobs", "career", "vacancies")

# Minimum characters of clean page text to treat a fetch as real evidence (not an empty/JS shell).
_MIN_PAGE_CHARS = 200
_MAX_PAGE_CHARS = 6000

# B-265: an own careers page saying this ends the cascade with a negative verdict. Deliberately
# narrow, literal phrasings — a studio writing "no positions open" means it, and the cost of a false
# positive is only a no-vacancy email (the safe side), while the cost of a false negative is naming
# roles that do not exist.
_NO_OPENINGS_RE = re.compile(
    r"(?:"
    r"no\s+(?:current(?:ly)?\s+|open\s+|available\s+)*(?:positions?|openings?|vacanc(?:y|ies)|roles?|jobs?)"
    r"(?:\s+(?:are\s+)?(?:open|available|currently))?"
    r"|(?:positions?|openings?|vacanc(?:y|ies)|roles?|jobs?)\s+(?:are\s+)?(?:currently\s+)?(?:not\s+available|closed)"
    r"|(?:we\s+are|we're)\s+not\s+(?:currently\s+)?hiring"
    r"|not\s+hiring\s+(?:at\s+the\s+moment|right\s+now|currently)"
    r"|нет\s+открытых\s+вакансий"
    r"|открытых\s+вакансий\s+нет"
    r"|ваканси[йи]\s+(?:сейчас\s+)?нет"
    r")",
    re.IGNORECASE,
)

# B-265: hiring talk in these places is a blog/social post, not an open-role listing. Dropped from
# the weak stages (c, d) — the careers page and ATS boards (a, b) are unaffected.
_WEAK_SOURCE_HOSTS: tuple[str, ...] = (
    "facebook.com", "fb.com", "twitter.com", "x.com", "instagram.com", "threads.net",
    "medium.com", "reddit.com", "vk.com", "t.me", "telegram.me", "youtube.com", "tiktok.com",
    "substack.com", "bsky.app", "mastodon.social", "discord.com", "discord.gg",
)
_WEAK_SOURCE_PATH_RE = re.compile(
    r"/(?:blog|blogs|news|press|posts?|pulse|articles?|stories)(?:/|$)", re.IGNORECASE
)


def _bare_domain(website: str | None) -> str | None:
    w = (website or "").strip()
    if not w:
        return None
    if not w.startswith("http"):
        w = "http://" + w
    host = (urlparse(w).netloc or "").lower().replace("www.", "")
    return host or None


def _company_base_url(website: str | None) -> str | None:
    w = (website or "").strip()
    if not w:
        return None
    if not w.startswith("http"):
        w = "http://" + w
    netloc = (urlparse(w).netloc or "").lower().replace("www.", "").strip()
    if not netloc or "." not in netloc:
        return None
    return f"https://{netloc}"


def careers_url_candidates(website: str | None) -> list[str]:
    """Company website -> candidate careers-page URLs, tried in order (a)."""
    base = _company_base_url(website)
    if not base:
        return []
    return [f"{base}/{path}" for path in CAREERS_PATHS]


# Generic corporate words that are NOT distinctive company identity (used for slug-collision
# guarding, finding #4).
_GENERIC_COMPANY_TOKENS: frozenset[str] = frozenset({
    "games", "game", "studio", "studios", "interactive", "entertainment", "digital", "media",
    "software", "tech", "technologies", "labs", "lab", "group", "team", "the", "ltd", "limited",
    "inc", "llc", "gmbh", "co", "company", "productions", "production",
})


def _company_distinctive_tokens(company_name: str) -> list[str]:
    """Company name -> its identifying tokens (generic corporate words removed). Empty when the
    name is all-generic (e.g. 'The Game Studio') — then ATS-slug guessing is too collision-prone."""
    toks = re.findall(r"[a-z0-9]+", (company_name or "").lower())
    return [t for t in toks if t not in _GENERIC_COMPANY_TOKENS and len(t) >= 3]


def _board_identifies_company(raw_text: str, company_name: str, website: str | None) -> bool:
    """Guard against slug collisions (finding #4): a guessed ATS board is trusted only when its
    raw content actually identifies THIS company — by website domain (strongest), by all
    multi-token distinctive names, or by a single long (>=6) distinctive token. A common short
    slug ('match', 'fusion') that lands on an unrelated org's real board fails this and is dropped.
    """
    t = (raw_text or "").lower()
    if not t:
        return False
    domain = _bare_domain(website)
    if domain:
        core = domain.split(".")[0]
        if core and len(core) >= 3 and core in t:
            return True
    distinctive = _company_distinctive_tokens(company_name)
    if len(distinctive) >= 2 and all(d in t for d in distinctive):
        return True
    if len(distinctive) == 1 and len(distinctive[0]) >= 6 and distinctive[0] in t:
        return True
    return False


# Corporate suffixes to strip before slug-guessing (B-075): "Strikerz Inc." must not leak
# "Inc"/"Inc." into the slug — none of the raw/compact/hyphenated forms matched the real board
# slug ("strikerz") while the suffix was still attached, and the trailing dot from "Inc."
# produced a broken double-dot hostname ("strikerzinc..huntflow.io").
_CORP_SUFFIX_RE = re.compile(
    r"[,\s]+(inc|ltd|llc|gmbh|co|corp|corporation|limited)\.?$", re.IGNORECASE
)

# Parenthesized content (ticker symbols etc., e.g. "Nexters ($GDEV)") is not part of the brand
# name and must not leak into the slug.
_PAREN_RE = re.compile(r"\([^)]*\)")


def company_slug_candidates(company_name: str) -> list[str]:
    """Company name -> candidate ATS slugs, tried in order (b). Different ATS platforms use
    different casing/formatting conventions (e.g. Ashby keeps the brand name as-is), so we try
    a small set of reasonable variants rather than committing to one normalization. Corporate
    suffixes and parenthesized ticker symbols are stripped first (B-075) since they are never
    part of a real ATS board slug and otherwise leak stray punctuation into the hostname."""
    name = (company_name or "").strip()
    if not name:
        return []
    name = _PAREN_RE.sub("", name).strip()
    name = _CORP_SUFFIX_RE.sub("", name).strip()
    if not name:
        return []
    compact = re.sub(r"[^A-Za-z0-9]+", "", name)
    hyphenated = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    candidates = [name.replace(" ", ""), compact, hyphenated]
    slugs: list[str] = []
    for s in candidates:
        if s and s not in slugs:
            slugs.append(s)
    return slugs


def ashby_job_board_url(slug: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"


def greenhouse_job_board_url(slug: str) -> str:
    return f"https://job-boards.eu.greenhouse.io/{slug}"


def huntflow_job_board_url(slug: str) -> str:
    return f"https://{slug.lower()}.huntflow.io"


def pinpoint_job_board_url(slug: str) -> str:
    return f"https://{slug.lower()}.pinpointhq.com"


def _vacancy_queries(company_name: str, website: str | None) -> list[str]:
    queries = [
        f'"{company_name}" careers OR jobs OR hiring OR vacancies',
        f'"{company_name}" hiring "game developer" OR "game artist" OR unity OR unreal OR "game designer"',
    ]
    domain = _bare_domain(website)
    if domain:
        queries.append(f"site:{domain} careers OR jobs OR vacancies OR join")
    return queries


def _fetch_raw(url: str) -> str:
    """Plain HTTP GET, text body or '' on any failure (network, non-200, empty)."""
    try:
        import httpx

        r = httpx.get(url, timeout=15, follow_redirects=True, headers=_FETCH_HEADERS)
        if r.status_code != 200 or not r.text:
            return ""
        return r.text
    except Exception as e:
        logger.info(f"vacancy radar fetch miss for {url}: {e}")
        return ""


def _corpus_from_careers_page(website: str | None) -> tuple[list[str], list[str]]:
    """(a) Company's own careers page — first candidate URL that yields real page text wins."""
    from app.services.company_source_extractor import _extract_page_text

    for url in careers_url_candidates(website):
        text = _extract_page_text(url)
        if text and len(text) >= _MIN_PAGE_CHARS:
            return [f"[Company careers page] {text[:_MAX_PAGE_CHARS]} ({url})"], [url]
    return [], []


def careers_page_declares_no_openings(text: str) -> bool:
    """B-265: does the company's own careers page explicitly state it has no open roles?

    Pure and deterministic — the phrasing is checked, never inferred by an LLM. True ends the
    cascade with a negative verdict: no weaker source may claim roles for this company."""
    return bool(_NO_OPENINGS_RE.search(text or ""))


def is_weak_hiring_source(url: str) -> bool:
    """B-265: a blog post, news item or social-network post about hiring is not an open role.

    Applies to the weak stages only (LinkedIn-snippet + general web search) — the careers page and
    ATS job boards are structured listings and are never filtered here."""
    u = (url or "").strip()
    if not u:
        return True
    if not u.startswith("http"):
        u = "https://" + u
    try:
        parsed = urlparse(u)
    except ValueError:
        return True
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in _WEAK_SOURCE_HOSTS):
        return True
    return bool(_WEAK_SOURCE_PATH_RE.search(parsed.path or ""))


def _no_openings_signal(source_urls: list[str]) -> dict[str, Any]:
    """Negative verdict from the company's own careers page (B-265). Persisted like a positive
    signal (the caller stores any truthy result), so the wave does not re-scan a studio that has
    already said it is not hiring — and `open_roles` stays empty, which is what routes the email to
    the no-vacancy template (email_kind_for) and makes any named role an invented_role."""
    return {
        "is_hiring": False,
        "declared_no_openings": True,
        "open_roles": [],
        "summary": "Careers page states there are no open positions.",
        "sources": sorted(set(source_urls))[:10],
    }


def _parse_ashby_jobs(raw: str) -> list[dict[str, str]]:
    """Parse Ashby's public job-board JSON (jobs[].title/location). Pure — no network."""
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except (ValueError, TypeError):
        return []
    jobs = obj.get("jobs") if isinstance(obj, dict) else None
    if not isinstance(jobs, list):
        return []
    out: list[dict[str, str]] = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        title = (j.get("title") or "").strip()
        if not title:
            continue
        out.append({"title": title, "location": (j.get("location") or "").strip()})
    return out


def _ashby_jobs(slug: str) -> list[dict[str, str]]:
    """Fetch + parse an Ashby job board by slug. Returns [] on any failure."""
    return _parse_ashby_jobs(_fetch_raw(ashby_job_board_url(slug)))


def _corpus_from_ats_patterns(
    company_name: str, website: str | None = None
) -> tuple[list[str], list[str]]:
    """(b) Known ATS platforms by company-name slug, tried in order per slug candidate. Each fetched
    board must pass _board_identifies_company before it is trusted (slug-collision guard, #4). No
    distinctive company token at all -> skip ATS guessing entirely (too collision-prone)."""
    from app.services.company_source_extractor import _extract_page_text

    if not _company_distinctive_tokens(company_name):
        return [], []

    for slug in company_slug_candidates(company_name):
        ashby_raw = _fetch_raw(ashby_job_board_url(slug))
        if ashby_raw and _board_identifies_company(ashby_raw, company_name, website):
            jobs = _parse_ashby_jobs(ashby_raw)
            if jobs:
                url = ashby_job_board_url(slug)
                lines = [f"[Ashby job board] {j['title']} — {j['location']} ({url})" for j in jobs[:20]]
                return lines, [url]

        for builder, label in (
            (greenhouse_job_board_url, "Greenhouse board"),
            (huntflow_job_board_url, "Huntflow board"),
            (pinpoint_job_board_url, "Pinpoint board"),
        ):
            url = builder(slug)
            text = _extract_page_text(url)
            if (
                text
                and len(text) >= _MIN_PAGE_CHARS
                and _board_identifies_company(text, company_name, website)
            ):
                return [f"[{label}] {text[:_MAX_PAGE_CHARS]} ({url})"], [url]
    return [], []


def _corpus_from_linkedin_jobs(company_name: str) -> tuple[list[str], list[str]]:
    """(c) LinkedIn Jobs snippets via search_web."""
    from app.services.search_service import search_configured, search_web

    if not search_configured():
        return [], []
    parts: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()
    query = f'"{company_name}" jobs site:linkedin.com/jobs'
    for hit in search_web(query, max_results=8, max_passages=3):
        url = hit.get("url") or ""
        if not url or url in seen or not hit.get("snippet") or "linkedin.com" not in url:
            continue
        if is_weak_hiring_source(url):
            continue  # B-265: a LinkedIn post/article, not a /jobs listing
        seen.add(url)
        parts.append(f"[LinkedIn Jobs] {hit.get('title', '')} — {hit.get('snippet', '')} ({url})")
        urls.append(url)
    return parts, urls


def _corpus_from_general_search(company_name: str, website: str | None) -> tuple[list[str], list[str]]:
    """(d) Original v1 behaviour: unrestricted web search — last resort."""
    from app.services.search_service import search_configured, search_web

    if not search_configured():
        return [], []
    seen: set[str] = set()
    parts: list[str] = []
    urls: list[str] = []
    for q in _vacancy_queries(company_name, website):
        for hit in search_web(q, max_results=5, max_passages=3):
            url = hit.get("url") or ""
            if url in seen or not hit.get("snippet"):
                continue
            if is_weak_hiring_source(url):
                continue  # B-265: blog/social/news chatter about hiring is not an open role
            seen.add(url)
            parts.append(f"[{hit.get('title', '')}] {hit.get('snippet', '')} ({url})")
            urls.append(url)
        if len(parts) >= 10:
            break  # enough evidence; stop spending search calls
    return parts, urls


def _extract_signal(
    company_name: str, corpus_parts: list[str], source_urls: list[str]
) -> dict[str, Any] | None:
    """Run the hiring-extraction LLM over one stage's corpus. Returns a signal only when the
    evidence shows present-tense roles with at least one concrete title (finding #9: is_hiring with
    an empty open_roles list is NOT a usable signal — never persist it). None otherwise, so the
    caller moves on to the next source (finding #10: a boilerplate careers page no longer masks a
    real ATS/LinkedIn board)."""
    from app.services.llm_gateway import complete_prompt_json_object
    from app.services.prompt_builder import build_prompt

    task = (
        f"You are screening whether the company '{company_name}' is CURRENTLY hiring, from raw "
        "evidence gathered from its careers page, an ATS job board, LinkedIn, or web search.\n"
        "- is_hiring=true ONLY when the evidence shows present-tense open roles (careers page "
        "with listings, live job posts, 'we are hiring' announcements). Old news about past "
        "hiring or generic 'join us' boilerplate without roles is NOT enough.\n"
        "- open_roles: list the concrete roles you can actually see in the evidence, with the "
        "source URL for each. Include location and country when the evidence shows where the "
        "role is based (e.g. a city name, 'remote', or a country). Never invent roles or "
        "locations.\n"
        "- summary: one short line naming the roles and where they were seen. Empty string when "
        "is_hiring is false.\n"
    )
    prompt = build_prompt(
        task=task,
        data={"company": company_name, "search_results": "\n".join(corpus_parts)},
        rules=[],
        output_schema=EXTRACTION_SCHEMA,
    )
    try:
        out = complete_prompt_json_object(prompt)
    except Exception as e:
        logger.warning(f"Vacancy radar extraction failed for {company_name}: {e}")
        return None
    if not isinstance(out, dict) or not out.get("is_hiring"):
        return None

    roles = out.get("open_roles")
    roles = [r for r in roles if isinstance(r, dict) and (r.get("role") or "").strip()] if isinstance(roles, list) else []
    if not roles:
        return None  # hiring claimed but no concrete role — ambiguous, don't persist (#9)
    return {
        "is_hiring": True,
        "open_roles": roles[:10],
        "summary": (out.get("summary") or "").strip(),
        "sources": sorted(set(source_urls))[:10],
    }


def collect_vacancy_signals(company_name: str, website: str | None = None) -> dict[str, Any] | None:
    """Search for open-vacancy evidence and extract a structured hiring signal.

    Returns {"is_hiring": bool, "open_roles": [...], "summary": str, "sources": [urls]}
    or None when there is no usable evidence anywhere in the cascade (nothing persisted,
    retried next run). Each stage is extracted on its own: a stage that yields text but no
    concrete roles does not short-circuit the more targeted stages that follow (#10).

    B-265: when the company's own careers page explicitly declares it has no open positions, the
    cascade stops there and returns a negative verdict (`declared_no_openings`, empty open_roles) —
    the weaker sources below are not consulted at all, because none of them may outvote the studio's
    own statement about its own hiring.
    """
    company_name = (company_name or "").strip()
    if not company_name:
        return None

    careers_parts, careers_urls = _corpus_from_careers_page(website)
    if careers_parts and any(careers_page_declares_no_openings(p) for p in careers_parts):
        logger.info(
            "Vacancy radar: %s declares no open positions on its own careers page — "
            "cascade stopped, weaker sources skipped (B-265).",
            company_name,
        )
        return _no_openings_signal(careers_urls)

    # Stages stay lazy (one fetch/search chain each) — a stage that yields a signal must not have
    # cost us the later stages' network calls.
    for stage in (
        lambda: (careers_parts, careers_urls),
        lambda: _corpus_from_ats_patterns(company_name, website),
        lambda: _corpus_from_linkedin_jobs(company_name),
        lambda: _corpus_from_general_search(company_name, website),
    ):
        corpus_parts, source_urls = stage()
        if not corpus_parts:
            continue
        signal = _extract_signal(company_name, corpus_parts, source_urls)
        if signal:
            return signal
    return None
