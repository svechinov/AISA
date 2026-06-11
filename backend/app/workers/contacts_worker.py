import logging
import os

from sqlalchemy.orm import Session

from app.utils.env_utils import env_int, env_truthy

from app.repositories.run_repo import get_run
from app.repositories.run_company_repo import list_run_companies_sparse
from app.services.apollo_service import apollo_configured, try_find_contacts_via_apollo
from app.services.contact_persistence_service import contacts_raw_for_pipeline_dicts
from app.services.llm_gateway import generate_json
from app.utils.contact_identity import contact_identity_key_from_dict
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import build_find_contacts_task
from app.services.rules_service import get_effective_rules_from_run

logger = logging.getLogger(__name__)


_truthy = env_truthy

# Default staleness floor. The same value appears as the example score in the deep-OSINT prompt
# rubric and as the discovery filter in osint_worker (imported from here) — one constant, не два литерала.
FRESHNESS_MIN_DEFAULT = 30


def _freshness_min() -> int:
    """Leaders below this freshness_score are flagged stale (same floor as discovery in osint_worker)."""
    return env_int("VALIDATE_FRESHNESS_MIN", FRESHNESS_MIN_DEFAULT)


def _smtp_probe_max() -> int:
    """Cap on SMTP RCPT probes per validate call (cost/time/IP-reputation control)."""
    return env_int("VALIDATE_SMTP_MAX", 25, min_value=1)


def _smtp_probe(email: str, mx_cache: dict[str, str | None]) -> str:
    """Verify one email via SMTP RCPT. Returns 'verified' | 'rejected' | 'unverified'.

    'unverified' when the domain has no MX or the probe could not reach a verdict (e.g. greylisting,
    timeout) — verify_email_smtp is conservative (returns False on any non-250), so we only call a
    failed probe 'rejected' after an actual SMTP exchange, not when MX lookup itself fails.
    """
    from app.services.hardcore_osint import get_mx_record, verify_email_smtp

    domain = email.split("@", 1)[1] if "@" in email else ""
    if not domain:
        return "unverified"
    if domain not in mx_cache:
        mx_cache[domain] = get_mx_record(domain)
    mx = mx_cache[domain]
    if not mx:
        return "unverified"
    try:
        return "verified" if verify_email_smtp(email, mx) else "rejected"
    except Exception as e:  # never let a probe abort validation of the whole batch
        logger.warning(f"validate SMTP probe failed for {email}: {e}")
        return "unverified"


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

    # Verification pass over format-valid contacts: annotate freshness + email verification.
    #  - freshness: leaders below the threshold are flagged stale (annotation only by default).
    #  - email_verification: emails discovered via the hardcore path are already SMTP-verified
    #    (carried in source_json). An optional SMTP probe (VALIDATE_SMTP_PROBE=1) verifies the rest,
    #    cached per email and capped per call. Already-verified/rejected emails are never re-probed.
    # Annotate-only by default — a provided/imported email is NOT downgraded to invalid on a failed
    # probe (corporate MX often greylist RCPT). Set VALIDATE_STRICT=1 to gate hard (stale/rejected
    # → invalid).
    fresh_min = _freshness_min()
    strict = _truthy("VALIDATE_STRICT")
    probe_enabled = _truthy("VALIDATE_SMTP_PROBE")
    probe_budget = _smtp_probe_max() if probe_enabled else 0
    mx_cache: dict[str, str | None] = {}

    kept_valid: list[dict] = []
    for contact in valid_contacts:
        fr = contact.get("freshness_score")
        is_stale = isinstance(fr, (int, float)) and fr < fresh_min
        if is_stale:
            contact["freshness_stale"] = True

        ver = contact.get("email_verification")
        if ver not in ("verified", "rejected"):
            if probe_enabled and probe_budget > 0:
                ver = _smtp_probe((contact.get("email") or "").strip().lower(), mx_cache)
                probe_budget -= 1
            else:
                ver = ver or "unverified"
            contact["email_verification"] = ver

        if strict and (is_stale or ver == "rejected"):
            contact["status"] = "invalid"
            invalid_contacts.append(contact)
        else:
            kept_valid.append(contact)

    return {
        "valid_contacts": kept_valid,
        "invalid_contacts": invalid_contacts,
    }
