from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.services.llm_gateway import generate_json
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_find_contacts_task
from app.services.rules_service import get_effective_rules_from_run


def find_contacts(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "find_contacts")
    task = build_find_contacts_task(run)

    prompt = build_prompt(
        task=task,
        data=step_input,
        rules=rules,
        output_schema={
            "contacts": [
                {
                    "company": "string",
                    "website": "string",
                    "name": "string",
                    "role": "string",
                    "email": "string",
                }
            ]
        },
    )

    return generate_json(prompt)


def validate_contacts(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    contacts = step_input.get("contacts", [])
    valid_contacts = []
    invalid_contacts = []
    seen = set()

    for contact in contacts:
        email = (contact.get("email") or "").strip().lower()
        key = ((contact.get("company") or "").strip().lower(), email)

        if not email or "@" not in email:
            contact["status"] = "invalid"
            invalid_contacts.append(contact)
            continue

        if key in seen:
            contact["status"] = "invalid"
            invalid_contacts.append(contact)
            continue

        seen.add(key)
        contact["status"] = "valid"
        valid_contacts.append(contact)

    return {
        "valid_contacts": valid_contacts,
        "invalid_contacts": invalid_contacts,
    }
