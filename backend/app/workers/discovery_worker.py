import logging
import json
from sqlalchemy.orm import Session
from app.models.run_company import RunCompany
from app.services.llm_gateway import complete_prompt_json_object
from app.services.tavily_osint import get_tavily_client

logger = logging.getLogger(__name__)

def agentic_company_discovery(db: Session, run_id: int, segment: str, count: int = 5) -> dict:
    """
    Step 3 of Deep Research:
    1. Generate search strategies based on the segment.
    2. Fetch URLs via Tavily.
    3. Scrape pages (via Tavily advanced or Firecrawl).
    4. Compress HTML using Headroom.
    5. Score via ICP-Scorecard.
    6. Add high-scoring companies to the database.
    """
    logger.info(f"Starting Agentic Company Discovery for run_id={run_id}, segment={segment}")
    
    # 1. Generate Search Strategies
    strategy_prompt = f"""
You are an elite B2B SDR Strategist. The user wants to find companies in this segment: "{segment}".
Generate 3 distinct search queries to find lists or directories of these companies in Russia.
For example, if segment is "IT integrators", queries might be "Топ IT-интеграторов России 2024", "Участники выставки Связь IT", "Список резидентов Сколково IT".
Return strict JSON:
{{
    "queries": ["query1", "query2", "query3"]
}}
"""
    strategy_json = complete_prompt_json_object(strategy_prompt)
    queries = strategy_json.get("queries", [])
    if not queries:
        return {"status": "error", "message": "Failed to generate strategies."}

    client = get_tavily_client()
    if not client:
        return {"status": "error", "message": "Tavily API key missing."}

    discovered_urls = {}
    
    # 2. Search Tavily
    for q in queries:
        try:
            logger.info(f"Discovery Query: {q}")
            response = client.search(query=q, search_depth="basic", max_results=5)
            for res in response.get("results", []):
                url = res.get("url")
                if url and "youtube" not in url and "vk.com" not in url:
                    discovered_urls[url] = res.get("content", "")
        except Exception as e:
            logger.warning(f"Tavily search failed for query '{q}': {e}")

    # 3. Score against ICP Scorecard
    added_companies = 0
    rejected = 0
    
    # Compress using headroom
    try:
        from headroom import compress
        headroom_available = True
    except ImportError:
        headroom_available = False
        
    for url, content in list(discovered_urls.items())[:count*2]:  # Test a subset
        if headroom_available and len(content) > 500:
            content = compress(content)
            
        score_prompt = f"""
Evaluate if this company matches the target segment: "{segment}".
Website: {url}
Snippet: {content}

Return strict JSON:
{{
    "is_b2b": true/false,
    "company_name": "extracted name or null",
    "icp_score": int (0 to 10),
    "reasoning": "short explanation"
}}
"""
        score_json = complete_prompt_json_object(score_prompt)
        icp_score = score_json.get("icp_score", 0)
        cname = score_json.get("company_name")
        
        if icp_score >= 8 and cname:
            # Check if exists
            exists = db.query(RunCompany).filter_by(run_id=run_id, name=cname).first()
            if not exists:
                idx = db.query(RunCompany).filter_by(run_id=run_id).count() + 1
                new_comp = RunCompany(
                    run_id=run_id,
                    collect_index=idx,
                    name=cname,
                    website=url,
                    ai_fit_status="approved",
                    ai_fit_reason=score_json.get("reasoning", "")
                )
                db.add(new_comp)
                added_companies += 1
                if added_companies >= count:
                    break
        else:
            rejected += 1

    db.commit()
    logger.info(f"Discovery complete. Added {added_companies}, rejected {rejected}.")
    return {
        "status": "success",
        "added": added_companies,
        "rejected": rejected,
        "queries_used": queries
    }
