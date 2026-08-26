import logging
from typing import Any
from sqlalchemy.orm import Session
from app.models.contact import Contact
from app.services.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

LPR_OSINT_SCHEMA = {
    # B-063: top of the geo-segment cascade (geo_segment_service.resolve_geo_segment) — the
    # recipient's OWN city/country, when visible in the evidence (e.g. "Limassol, Cyprus",
    # "Belgrade" — not the company's HQ). Empty when the search results don't show it; the
    # cascade then falls back to the company's office city.
    "recipient_location": "string — the person's own city/country if visible, else empty",
    "career_summary": "string",
    "recent_quotes_or_posts": "string",
    "key_interests_or_focus_areas": "string",
    "notable_achievements": "string"
}


def _person_queries(name: str, company: str, role: str, language: str) -> list[str]:
    """Relaxation ladder: strict → name+company → name+role → social profiles. Keywords and
    social domains follow the campaign language: Russian keywords steer Yandex into Runet
    (VK/TG/regional press); for everything else English keywords + LinkedIn/X cover the
    global web that Tavily indexes."""
    if (language or "").strip().lower() == "russian":
        return [
            f"{name} {company} интервью OR статья OR выступление OR новости",
            f"{name} {company}",
            f"{name} {role} {company}".strip(),
            f"{name} {company} vk.com OR t.me OR ok.ru",
        ]
    return [
        f"{name} {company} interview OR podcast OR talk OR article",
        f"{name} {company}",
        f"{name} {role} {company}".strip(),
        f"{name} {company} linkedin.com OR twitter.com OR x.com",
    ]


def _person_search_corpus(name: str, company: str, role: str, language: str = "English") -> str:
    """Tiered person search via the search provider. Returns a concatenated corpus,
    or '' when truly nothing is found."""
    from app.services.search_service import search_web

    name = (name or "").strip()
    company = (company or "").strip()
    role = (role or "").strip()
    if not name:
        return ""

    seen: set[str] = set()
    corpus_parts: list[str] = []
    for q in _person_queries(name, company, role, language):
        for hit in search_web(q, max_results=6, max_passages=5):
            if hit["url"] in seen or not hit.get("snippet"):
                continue
            seen.add(hit["url"])
            corpus_parts.append(f"[{hit['title']}] {hit['snippet']} ({hit['url']})")
        if len(corpus_parts) >= 8:
            break  # enough grounding; stop spending search calls
    return "\n".join(corpus_parts)


def perform_deep_lpr_osint(db: Session, contact: Contact) -> dict[str, Any]:
    # Campaign language drives both the search keywords and the dossier output language.
    custom_task = None
    language = "English"
    try:
        from app.models.run_setup import RunSetup
        setup = db.query(RunSetup).filter(RunSetup.run_id == contact.run_id).first()
        if setup:
            language = (setup.language or "English").strip() or "English"
            if setup.deep_osint_prompt:
                custom_task = setup.deep_osint_prompt
    except Exception as e:
        logger.warning(f"Could not load run_setup for deep LPR OSINT: {e}")

    # 1. Search (provider order from SEARCH_PROVIDER_PRIORITY; queries follow the language)
    raw_dossier = _person_search_corpus(contact.name, contact.company, contact.role, language)
    if not raw_dossier.strip():
        return {"error": "No relevant public information found for this person."}

    # 2. Extract structured profile via LLM
    task = custom_task or (
        "You are an expert OSINT profiler. Analyze the raw search results about this person "
        "and build a structured personal dossier.\n"
        "Focus: professional background, recent public statements/posts, talks, "
        "key interests and focus areas, and the person's own city/country if it is visible "
        "(recipient_location) — distinct from the company's headquarters.\n"
        f"WRITE ALL field values IN {language.upper()}. If specific information is missing, leave "
        "the field empty or write 'Not found'. Never invent facts that are not in the search "
        "results.\n\n"
    )
    task += f"\nRaw search results:\n{raw_dossier}"

    data = {
        "person": contact.name,
        "company": contact.company,
        "role": contact.role
    }

    prompt = build_prompt(
        task=task,
        data=data,
        rules=[],
        output_schema=LPR_OSINT_SCHEMA
    )

    try:
        from app.services.llm_gateway import complete_prompt_json_object
        extracted = complete_prompt_json_object(prompt, task_kind="lpr_osint")
    except Exception as e:
        logger.exception(f"LLM extraction failed for LPR {contact.name}")
        return {"error": f"LLM parsing failed: {str(e)}"}

    return extracted
