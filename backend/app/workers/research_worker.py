import logging

from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.company_website_check import collect_companies_annotate_llm_flags
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_collect_companies_task
from app.services.rules_service import get_effective_rules_from_run

logger = logging.getLogger(__name__)


def collect_companies(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "collect_companies")
    continuation = bool(step_input.get("continuation"))
    task = build_collect_companies_task(run, continuation=continuation)

    data = dict(step_input) if isinstance(step_input, dict) else {}
    raw = list_run_companies_sparse(db, run_id)
    prior = [x for x in raw if isinstance(x, dict)]
    if prior:
        data["companies"] = prior

    prompt = build_prompt(
        task=task,
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
