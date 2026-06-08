import os
from tavily import TavilyClient

def get_tavily_client() -> TavilyClient | None:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    return TavilyClient(api_key=api_key)

def get_company_dossier(company_name: str, website: str, run=None) -> str:
    client = get_tavily_client()
    if not client:
        return "Tavily API key not configured. OSINT skipped."
        
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
        response = client.search(
            query=query,
            search_depth="advanced",
            include_answer=True,
            max_results=5
        )
        
        context = ""
        if response.get("answer"):
            context += f"Summary: {response['answer']}\n"
        for result in response.get("results", []):
            context += f"Source ({result.get('url')}): {result.get('content')}\n"
            
        # Compress the context using Headroom to save tokens and reduce hallucinations
        try:
            from headroom import compress
            import logging
            logger = logging.getLogger(__name__)
            original_len = len(context)
            # If the context is very large, Headroom will compress it.
            context = compress(context)
            logger.info(f"Headroom compressed OSINT context from {original_len} to {len(context)} characters")
        except Exception as e:
            # Fallback if headroom is not installed or fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Headroom compression skipped/failed: {e}")
            
        from app.services.llm_gateway import complete_prompt_json_object
        import json
        
        prompt = f"""
You are an expert OSINT analyst. Analyze the following OSINT data about {company_name} ({website}).
Extract key facts, business triggers, and hypotheses for a B2B sales pitch. 
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
    client = get_tavily_client()
    if not client:
        return None
        
    query = f"Email address for {contact_name} at {company_name} {website} contact"
    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=5
        )
        
        # Simple extraction looking for @
        # In a production system, this would be routed back to the LLM to parse cleanly, 
        # or use a dedicated email hunting API (like Hunter.io), but this provides a fallback baseline.
        import re
        for result in response.get("results", []):
            content = result.get('content', '')
            emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', content)
            if emails:
                return emails[0]
                
        return None
    except Exception:
        return None
