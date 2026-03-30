from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_collect_companies_task
from app.services.rules_service import get_effective_rules_from_run


def collect_companies(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "collect_companies")
    task = build_collect_companies_task(run)

    prompt = build_prompt(
        task=task,
        data=step_input,
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

    return generate_json(prompt)
