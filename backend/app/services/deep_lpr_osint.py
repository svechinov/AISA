import logging
from typing import Any
from sqlalchemy.orm import Session
from app.models.contact import Contact
from app.services.tavily_osint import get_tavily_client
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

LPR_OSINT_SCHEMA = {
    "career_summary": "string",
    "recent_quotes_or_posts": "string",
    "key_interests_or_focus_areas": "string",
    "notable_achievements": "string"
}

def perform_deep_lpr_osint(db: Session, contact: Contact) -> dict[str, Any]:
    client = get_tavily_client()
    if not client:
        return {"error": "Tavily API key not configured."}
    
    # 1. Search Tavily
    query = f"\"{contact.name}\" \"{contact.company}\" (LinkedIn OR interview OR article OR speaker OR blog)"
    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            include_answer=True,
            max_results=5
        )
    except Exception as e:
        logger.exception(f"Tavily search failed for LPR {contact.name}")
        return {"error": f"Search failed: {str(e)}"}
    
    raw_dossier = ""
    if response.get("answer"):
        raw_dossier += f"Answer: {response['answer']}\n\n"
    
    for result in response.get("results", []):
        raw_dossier += f"Title: {result.get('title')}\nContent: {result.get('content')}\n\n"
        
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
        "You are an expert OSINT profiler. Analyze the raw search results for the target individual and extract a structured personal dossier.\n"
        "Focus on their professional background, recent public statements, speaking engagements, and key focus areas.\n"
        "If you cannot find specific information, leave the field empty or state 'Not found'.\n\n"
    )
    task += f"\nRaw Search Results:\n{raw_dossier}"
    
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
