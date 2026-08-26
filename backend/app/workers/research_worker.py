import logging

from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.apollo_service import apollo_configured, try_collect_companies_via_apollo
from app.repositories.excluded_company_repo import filter_excluded_companies
from app.services.company_website_check import collect_companies_annotate_llm_flags
from app.services.human_ui_activity import push_human_ui_activity
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_collect_companies_task
from app.services.rules_service import get_effective_rules_from_run

logger = logging.getLogger(__name__)


from app.services.tavily_osint import get_tavily_client


def _drop_excluded(db: Session, run_id: int, out: dict) -> dict:
    """B-264: strip companies that are already on the cross-run exclusion registry.

    A "not our segment" verdict used to die with its run, so the next Apollo sweep with the same
    filters re-collected the same competitor / job board / PSL-locked subsidiary and paid for
    research on it again. Applied to BOTH discovery paths (Apollo and Tavily/LLM) — the registry is
    about the company, not about who found it."""
    companies = out.get("companies") if isinstance(out, dict) else None
    if not isinstance(companies, list) or not companies:
        return out
    try:
        kept, dropped = filter_excluded_companies(db, companies, run_id=run_id)
    except Exception:
        # Fail open: the registry saves research spend, it is not a safety gate — a DB hiccup must
        # not abort a collection step (the worst case is re-collecting a company we would drop).
        logger.exception("exclusion registry unavailable — companies kept as collected (B-264)")
        return out
    if dropped:
        logger.info(
            "collect_companies run_id=%s: %d company row(s) dropped by the exclusion registry (B-264)",
            run_id,
            len(dropped),
        )
        names = ", ".join(f"{(c.get('name') or '—')} ({hit.reason})" for c, hit in dropped[:8])
        push_human_ui_activity(
            db,
            run_id,
            f"Реестр исключений: отброшено компаний — {len(dropped)}: {names}"
            + ("…" if len(dropped) > 8 else "."),
        )
    result = dict(out)
    result["companies"] = kept
    return result


def collect_companies(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "collect_companies")
    continuation = bool(step_input.get("continuation"))
    task = build_collect_companies_task(run, continuation=continuation)

    # --- Apollo-first company discovery (opt-in via APOLLO_API_KEY) ---
    # Apollo has structured firmographic search (industry + location + size), so it is the
    # preferred source when configured. Unlike the old main behavior, a None/empty result
    # falls through to the Tavily/LLM path below instead of dead-ending the step.
    if apollo_configured():
        try:
            apollo_raw = try_collect_companies_via_apollo(
                db, run_id, run, continuation=continuation
            )
        except Exception:
            logger.exception("Apollo company discovery failed — falling back to Tavily/LLM")
            apollo_raw = None
        if apollo_raw and apollo_raw.get("companies"):
            apollo_raw = _drop_excluded(db, run_id, apollo_raw)
            if apollo_raw.get("companies"):
                return collect_companies_annotate_llm_flags(apollo_raw, run_id=run_id)
            logger.info("Apollo companies were all on the exclusion registry — falling back to Tavily/LLM")
        logger.info("Apollo returned no companies — falling back to Tavily/LLM discovery")

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
    out = _drop_excluded(db, run_id, out if isinstance(out, dict) else {})
    return collect_companies_annotate_llm_flags(out, run_id=run_id)
