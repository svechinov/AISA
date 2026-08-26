import os
from tavily import TavilyClient

def get_tavily_client() -> TavilyClient | None:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    return TavilyClient(api_key=api_key)

def get_company_dossier(company_name: str, website: str, run=None) -> str:
    from app.services.search_service import search_configured
    if not search_configured():
        return "No search provider configured. OSINT skipped."

    site_ctx = f" (website: {website})" if website and website.strip() else ""

    # Use custom prompt + language from run if available
    query_template = None
    custom_sources = None
    language = "English"
    if run and run.run_setup:
        if run.run_setup.osint_prompt:
            query_template = run.run_setup.osint_prompt
        if run.run_setup.company_search_prompt:
            custom_sources = run.run_setup.company_search_prompt
        if (run.run_setup.language or "").strip():
            language = run.run_setup.language.strip()

    if query_template:
        query = query_template.replace("{{company}}", company_name).replace("{{website}}", website)
    else:
        query = (
            f"Find deep business intelligence on {company_name}{site_ctx}. "
            "Focus on: 1. Recent news, launches, funding, strategy. 2. Growth and team signals "
            "(expansion, restructuring, hiring plans, key departures). "
            "3. Key decision makers (CEO, founders, HR/People lead). "
        )
        if language.lower() == "russian":
            query += "Также на русском: найти стратегию развития, новости и кадровые изменения."

    if custom_sources:
        query += f"\n\nAdditional OSINT sources/instructions from user: {custom_sources}"

    try:
        # Search via the provider layer (order from SEARCH_PROVIDER_PRIORITY).
        from app.services.search_service import search_web
        hits = search_web(query, max_results=6, max_passages=5)
        if not hits:
            # No corpus → no dossier. Feeding an empty context to the LLM yields a
            # syntactically valid dossier fabricated from nothing; the caller's guard
            # keys off '"error"' to skip persisting, so retries stay possible.
            return f'{{"error": "OSINT search returned no results for {company_name} — dossier not generated"}}'

        context = ""
        for h in hits:
            context += f"Source ({h.get('url')}): [{h.get('title','')}] {h.get('snippet','')}\n"

        from app.services.llm_gateway import complete_prompt_json_object
        import json

        prompt = f"""
You are an expert OSINT analyst. Analyze the following OSINT data about {company_name} ({website}).
Extract key facts, business triggers, and hypotheses for a B2B sales pitch.
LANGUAGE: write ALL text values (facts, hypotheses, triggers) in {language.upper()} (keep the JSON keys in English).
CRITICAL: You must provide strict evidence for each fact.
Return ONLY a valid JSON object with this exact structure:
{{
  "hypotheses": ["hypothesis 1", "hypothesis 2"],
  "triggers": ["trigger 1", "trigger 2"],
  "evidence": [
    {{"fact": "statement of fact", "source_url": "url", "confidence_score": 95}}
  ]
}}

OSINT Data:
{context}
"""
        json_obj = complete_prompt_json_object(prompt)
        return json.dumps(json_obj, ensure_ascii=False, indent=2)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f'{{"error": "OSINT profiling failed: {str(e)}"}}'

def discover_contact_email(company_name: str, website: str, contact_name: str, language: str = "English") -> str | None:
    # Search via the provider layer; query keywords follow the campaign language.
    from app.services.search_service import search_web

    if (language or "").strip().lower() == "russian":
        query = f"{contact_name} {company_name} email почта контакты"
    else:
        query = f"{contact_name} {company_name} email contact"
    try:
        import re
        for hit in search_web(query, max_results=5, max_passages=5):
            emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', hit.get("snippet", ""))
            if emails:
                return emails[0]
        return None
    except Exception:
        return None
