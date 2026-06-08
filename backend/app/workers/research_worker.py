import logging

from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.apollo_service import try_collect_companies_via_apollo
from app.services.company_website_check import collect_companies_annotate_llm_flags
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_collect_companies_task
from app.services.rules_service import get_effective_rules_from_run

logger = logging.getLogger(__name__)


from app.services.tavily_osint import get_tavily_client

def collect_companies(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "collect_companies")
    continuation = bool(step_input.get("continuation"))
    task = build_collect_companies_task(run, continuation=continuation)

    apollo_raw = try_collect_companies_via_apollo(
        db, run_id, run, continuation=continuation
    )
    if apollo_raw is not None:
        return collect_companies_annotate_llm_flags(apollo_raw, run_id=run_id)

    data = dict(step_input) if isinstance(step_input, dict) else {}
    raw = list_run_companies_sparse(db, run_id)
    prior = [x for x in raw if isinstance(x, dict)]
    if prior:
        data["companies"] = prior

    # --- Agentic Company Discovery via Tavily ---
    client = get_tavily_client()
    search_context = ""
    if client:
        # 1. Generate 3 Search Queries
        query_prompt = build_prompt(
            task=f"Generate exactly 3 precise web search queries to find companies matching the following profile.\n\nProfile Context:\n{task}",
            data={},
            rules=[],
            output_schema={"queries": ["query1", "query2", "query3"]}
        )
        try:
            query_json = generate_json(query_prompt)
            queries = query_json.get("queries", [])
        except Exception as e:
            logger.error(f"Failed to generate queries: {e}")
            queries = []

        # 2. Execute Searches
        for q in queries[:3]:
            try:
                res = client.search(query=q, search_depth="basic", max_results=10)
                search_context += f"### Search Results for: {q}\n"
                for r in res.get("results", []):
                    search_context += f"- [{r.get('title')}]({r.get('url')}): {r.get('content')}\n"
            except Exception as e:
                logger.error(f"Tavily search failed for {q}: {e}")
    else:
        logger.warning("Tavily client not configured, falling back to LLM memory for company discovery.")

    # 3. Extract & Validate
    if search_context:
        extraction_task = (
            f"{task}\n\n"
            "CRITICAL AGENT INSTRUCTION: You must extract companies ONLY from the Search Results provided below. "
            "Validate each company against the target profile requirements (ICP). If a company does not strictly fit, skip it. "
            "Do not invent or guess companies from memory.\n\n"
            f"{search_context}"
        )
    else:
        extraction_task = task

    prompt = build_prompt(
        task=extraction_task,
        data=data,
        rules=rules,
        output_schema={
            "companies": [
                {
                    "name": "string",
                    "website": "string",
                }
            ]
        },
    )

    out = generate_json(prompt)
    return collect_companies_annotate_llm_flags(out if isinstance(out, dict) else {}, run_id=run_id)
