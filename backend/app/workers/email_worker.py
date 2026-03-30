import logging

from sqlalchemy.orm import Session

from app.repositories.contact_repo import list_sendable_contacts_by_run
from app.repositories.email_draft_repo import find_draft_by_contact_id
from app.repositories.run_repo import get_run, update_run_master_email_variants
from app.services.llm_gateway import generate_json
from app.services.outreach_personalize import (
    MASTER_VARIANT_COUNT,
    normalize_variants_payload,
    personalize_outbound,
    select_variant_for_contact,
)
from app.services.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

# Three full, distinct bodies (no manual string-mixing); each passes per-variant validation.
FALLBACK_MASTER_VARIANTS: list[dict[str, str]] = [
    {
        "subject": "Quick intro — possible fit",
        "body": (
            "Reaching out regarding a potential collaboration.\n\n"
            "We see overlap between your direction and a focused initiative on our side — not a mass "
            "mailing, but a concrete reason to compare notes.\n\n"
            "If it helps, we can start with a tight written summary or a ten-minute call; you choose "
            "the lighter option.\n\n"
            "If this lands at a bad time, feel free to skip — we will not push repeated pings.\n\n"
            "Thanks for reading."
        ),
    },
    {
        "subject": "One question on timing",
        "body": (
            "I am writing to test whether now is a reasonable moment to talk about a narrow partnership "
            "angle.\n\n"
            "The reason is specific: we are pairing organizations like yours with a practical offer that "
            "does not depend on a long sales cycle or a heavy deck.\n\n"
            "If you want detail first, say the word and we will send a short outline; if you prefer a "
            "call, we can book something small.\n\n"
            "If this is simply not on your radar, a one-line “not now” is enough — we will close the thread "
            "cleanly.\n\n"
            "Either way, appreciated."
        ),
    },
    {
        "subject": "Straightforward note on working together",
        "body": (
            "This is a direct note about whether working together could make sense in the near term.\n\n"
            "We are not pitching a vague “synergy” story — there is a defined outcome we pursue with a small "
            "set of partners, and your profile matches the brief we use internally.\n\n"
            "We can be flexible on format: email back-and-forth, one call, or materials only — whatever fits "
            "how you like to evaluate opportunities.\n\n"
            "No obligation to reply at length; a short yes/no on interest is already useful.\n\n"
            "Best"
        ),
    },
]


def _validated_fallback_variants() -> list[dict[str, str]]:
    wrapped = {"variants": FALLBACK_MASTER_VARIANTS}
    return normalize_variants_payload(wrapped)


def _call_llm_for_master_variants(brief: str) -> list[dict[str, str]]:
    task = (
        f"{brief}\n\n"
        "Task:\n"
        "Write 3 different outreach emails.\n\n"
        "Requirements:\n"
        "- each must be meaningfully different in structure and phrasing (not minor word swaps)\n"
        "- same campaign goal across all three\n"
        "- 5–8 sentences in each body; clear value proposition; direct and human\n"
        "- do not include a salutation line (no “Hi,” / “Hello,” / recipient name) — it is added later\n"
        "- you may use {{company}} in the body where the company name should appear\n\n"
        "Avoid across all variants:\n"
        "- generic openers (“hope you are well”, “I hope this email finds you well”)\n"
        "- long throat-clearing introductions\n"
        "- buzzword stacks\n"
        "- markdown unless necessary\n\n"
        "Return JSON only with this shape:\n"
        "{\n"
        '  "variants": [\n'
        '    {"subject": "...", "body": "..."},\n'
        '    {"subject": "...", "body": "..."},\n'
        '    {"subject": "...", "body": "..."}\n'
        "  ]\n"
        "}"
    )

    prompt = build_prompt(
        task=task,
        data={"master_prompt": brief},
        rules=[],
        output_schema={
            "variants": [
                {"subject": "string", "body": "string"},
                {"subject": "string", "body": "string"},
                {"subject": "string", "body": "string"},
            ]
        },
    )

    out = generate_json(prompt, task_kind="master_email")
    return normalize_variants_payload(out)


def generate_master_email_draft(
    db: Session,
    run_id: int,
    workflow_name: str,
    step_input: dict,
) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    brief = run.master_prompt or ""
    variants: list[dict[str, str]]

    try:
        variants = _call_llm_for_master_variants(brief)
    except Exception as exc:
        logger.warning(
            "Master email variants LLM or validation failed for run_id=%s; using %s-variant fallback: %s",
            run.id,
            MASTER_VARIANT_COUNT,
            exc,
            exc_info=False,
        )
        variants = _validated_fallback_variants()

    update_run_master_email_variants(db, run, variants)
    db.refresh(run)
    logger.info("MASTER EMAIL run_id=%s: %s", run.id, run.master_email)

    return {"variants": variants, "variant_count": len(variants), "generated": True}


def _variants_from_run(run) -> list[dict[str, str]]:
    me = getattr(run, "master_email", None)
    if not isinstance(me, dict):
        raise ValueError(
            "run.master_email is missing or invalid. "
            "Complete generate_master_email_draft before generate_emails."
        )
    return normalize_variants_payload(me)


def generate_emails(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    sendable_contacts = list_sendable_contacts_by_run(db, run_id)

    variants = _variants_from_run(run)

    emails = []

    for contact in sendable_contacts:
        if find_draft_by_contact_id(db, run_id, contact.id):
            continue

        variant, variant_idx = select_variant_for_contact(run.id, contact.id, variants)
        logger.info(
            "EMAIL VARIANT run_id=%s contact_id=%s variant_idx=%s",
            run.id,
            contact.id,
            variant_idx,
        )
        subject, body = personalize_outbound(
            run.id,
            contact,
            variant["subject"],
            variant["body"],
        )

        emails.append(
            {
                "contact_id": contact.id,
                "company": contact.company,
                "to": contact.email,
                "subject": subject,
                "body": body,
            }
        )

    return {
        "emails": emails,
        "email_count": len(emails),
    }
