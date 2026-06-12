import logging
from typing import Any
from sqlalchemy.orm import Session
from app.models.contact import Contact
from app.services.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

LPR_OSINT_SCHEMA = {
    "career_summary": "string",
    "recent_quotes_or_posts": "string",
    "key_interests_or_focus_areas": "string",
    "notable_achievements": "string"
}

def _person_search_corpus(name: str, company: str, role: str) -> str:
    """Tiered RU search for a person via the search provider (Yandex primary — sees VK/TG/regional).

    Russian keywords (not English LinkedIn/blog which steer away from Runet) and a relaxation
    ladder so an obscure-but-real person (pilot: Шаройкина) still surfaces: strict -> name+role+
    region -> name in news. Returns a concatenated corpus, or '' when truly nothing is found.
    """
    from app.services.search_service import search_web

    name = (name or "").strip()
    company = (company or "").strip()
    role = (role or "").strip()
    if not name:
        return ""

    queries = [
        f"{name} {company} интервью OR статья OR выступление OR новости",
        f"{name} {company}",
        f"{name} {role} {company}".strip(),
        f"{name} {company} vk.com OR t.me OR ok.ru",
    ]
    seen: set[str] = set()
    corpus_parts: list[str] = []
    for q in queries:
        for hit in search_web(q, max_results=6, max_passages=5):
            if hit["url"] in seen or not hit.get("snippet"):
                continue
            seen.add(hit["url"])
            corpus_parts.append(f"[{hit['title']}] {hit['snippet']} ({hit['url']})")
        if len(corpus_parts) >= 8:
            break  # enough grounding; stop spending search calls
    return "\n".join(corpus_parts)


def perform_deep_lpr_osint(db: Session, contact: Contact) -> dict[str, Any]:
    # 1. Search (Yandex primary via search_service — Runet coverage; Tavily fallback)
    raw_dossier = _person_search_corpus(contact.name, contact.company, contact.role)
    if not raw_dossier.strip():
        return {"error": "No relevant public information found for this person."}

    # 2. Extract structured profile via LLM
    custom_task = None
    try:
        from app.models.run_setup import RunSetup
        setup = db.query(RunSetup).filter(RunSetup.run_id == contact.run_id).first()
        if setup and setup.deep_osint_prompt:
            custom_task = setup.deep_osint_prompt
    except Exception as e:
        logger.warning(f"Could not load custom deep_osint_prompt: {e}")

    task = custom_task or (
        "Ты эксперт-OSINT-профайлер. Проанализируй сырую поисковую выдачу о человеке и собери "
        "структурированное персональное досье.\n"
        "Фокус: профессиональный бэкграунд, недавние публичные высказывания/посты, выступления, "
        "ключевые интересы и зоны фокуса.\n"
        "ВСЕ значения полей пиши ПО-РУССКИ. Если конкретной информации нет — оставь поле пустым "
        "или укажи 'Не найдено'. Не выдумывай фактов, которых нет в выдаче.\n\n"
    )
    task += f"\nСырая поисковая выдача:\n{raw_dossier}"
    
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
        extracted = complete_prompt_json_object(prompt)
    except Exception as e:
        logger.exception(f"LLM extraction failed for LPR {contact.name}")
        return {"error": f"LLM parsing failed: {str(e)}"}
        
    return extracted
