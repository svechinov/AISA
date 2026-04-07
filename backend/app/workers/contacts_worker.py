from sqlalchemy.orm import Session

from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.apollo_service import apollo_configured, try_find_contacts_via_apollo
from app.services.contact_persistence_service import contacts_raw_for_pipeline_dicts
from app.services.llm_gateway import generate_json
from app.utils.contact_identity import contact_identity_key_from_dict
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_find_contacts_task
from app.services.rules_service import get_effective_rules_from_run


def find_contacts(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    rules = get_effective_rules_from_run(db, run_id, "find_contacts")
    task = build_find_contacts_task(run)

    # With APOLLO_API_KEY set, find_contacts uses Apollo only — never LLM for this step.
    if apollo_configured():
        apollo_out = try_find_contacts_via_apollo(db, run_id, run, step_input)
        return apollo_out if apollo_out is not None else {"contacts": []}

    companies = step_input.get("companies") if isinstance(step_input, dict) else None
    if not isinstance(companies, list):
        companies = []
    if not companies:
        companies = list_run_companies_sparse(db, run_id)
    grounded = [c for c in companies if isinstance(c, dict) and not c.get("llm_hallucination")]
    data = dict(step_input) if isinstance(step_input, dict) else {}
    data["companies"] = grounded

    prompt = build_prompt(
        task=task,
        data=data,
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
    if not isinstance(contacts, list):
        contacts = []
    if not contacts:
        contacts = contacts_raw_for_pipeline_dicts(db, run_id)

    # Same natural person (name + company + website) may appear with and without email in one LLM batch.
    # Do not emit invalid "no email" rows when that identity already has at least one email (order-independent).
    identities_with_email: set[str] = set()
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        email = (contact.get("email") or "").strip().lower()
        if email and "@" in email:
            ik = contact_identity_key_from_dict(contact)
            if ik:
                identities_with_email.add(ik)

    valid_contacts = []
    invalid_contacts = []
    seen_emails: set[str] = set()
    seen_no_email_identity: set[str] = set()

    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        email = (contact.get("email") or "").strip().lower()

        if not email or "@" not in email:
            ik = contact_identity_key_from_dict(contact)
            if ik and ik in identities_with_email:
                continue
            if ik and ik in seen_no_email_identity:
                continue
            if ik:
                seen_no_email_identity.add(ik)
            contact["status"] = "invalid"
            invalid_contacts.append(contact)
            continue

        # One row per email (same person with different company strings was creating UI duplicates).
        if email in seen_emails:
            contact["status"] = "invalid"
            invalid_contacts.append(contact)
            continue

        seen_emails.add(email)
        contact["status"] = "valid"
        valid_contacts.append(contact)

    return {
        "valid_contacts": valid_contacts,
        "invalid_contacts": invalid_contacts,
    }
