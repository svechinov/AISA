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
    
    # Use custom prompt from run if available
    query_template = None
    custom_sources = None
    if run and run.run_setup:
        if run.run_setup.osint_prompt:
            query_template = run.run_setup.osint_prompt
        if run.run_setup.company_search_prompt:
            custom_sources = run.run_setup.company_search_prompt
    
    if query_template:
        query = query_template.replace("{{company}}", company_name).replace("{{website}}", website)
    else:
        query = (
            f"Find deep business intelligence on {company_name}{site_ctx}. "
            "Focus on: 1. Recent news and 2026 strategy. 2. Management and HR challenges (e.g., expansion, restructuring, leadership training needs). 3. Key decision makers (CEO, HR Director). "
            "Также на русском: Найти стратегию развития, новости и кадровые изменения."
        )

    if custom_sources:
        query += f"\n\nAdditional OSINT sources/instructions from user: {custom_sources}"
    
    try:
        # Search via the R4 provider (Yandex-primary — Runet coverage for RU companies;
        # Tavily fallback). Replaces the direct Tavily call so RU sources are actually seen.
        from app.services.search_service import search_web
        hits = search_web(query, max_results=6, max_passages=5)

        context = ""
        for h in hits:
            context += f"Source ({h.get('url')}): [{h.get('title','')}] {h.get('snippet','')}\n"

        from app.services.llm_gateway import complete_prompt_json_object
        import json
        
        prompt = f"""
You are an expert OSINT analyst. Analyze the following OSINT data about {company_name} ({website}).
Extract key facts, business triggers, and hypotheses for a B2B sales pitch.
LANGUAGE: write ALL text values (facts, hypotheses, triggers) in RUSSIAN (keep the JSON keys in English).
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

def discover_contact_email(company_name: str, website: str, contact_name: str) -> str | None:
    # Search via the R4 provider (Yandex-primary). Russian query — the contact is RU.
    from app.services.search_service import search_web

    query = f"{contact_name} {company_name} email почта контакты"
    try:
        import re
        for hit in search_web(query, max_results=5, max_passages=5):
            emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', hit.get("snippet", ""))
            if emails:
                return emails[0]
        return None
    except Exception:
        return None
