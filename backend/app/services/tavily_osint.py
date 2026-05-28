import os
from tavily import TavilyClient

def get_tavily_client() -> TavilyClient | None:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    return TavilyClient(api_key=api_key)

def get_company_dossier(company_name: str, website: str) -> str:
    client = get_tavily_client()
    if not client:
        return "Tavily API key not configured. OSINT skipped."
        
    site_ctx = f" (website: {website})" if website and website.strip() else ""
    query = (
        f"Find deep business intelligence on {company_name}{site_ctx}. "
        "Focus on: 1. Recent news and 2026 strategy. 2. Management and HR challenges (e.g., expansion, restructuring, leadership training needs). 3. Key decision makers (CEO, HR Director)."
    )
    
    try:
        response = client.search(
            query=query,
            search_depth="advanced",
            include_answer=True,
            max_results=5
        )
        
        dossier = ""
        if response.get("answer"):
            dossier += f"### OSINT Summary\n{response['answer']}\n\n"
            
        dossier += "### Sources\n"
        for result in response.get("results", []):
            dossier += f"- {result.get('title', 'Link')} ({result.get('url')})\n"
            
        return dossier
    except Exception as e:
        return f"OSINT profiling failed: {str(e)}"

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
