import logging
import random

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.repositories.contact_repo import get_contact, list_sendable_contacts_by_run
from app.repositories.email_draft_repo import (
    find_draft_by_contact_id,
    get_email_draft,
    update_email_draft_outreach_regenerate,
)
from app.repositories.run_repo import get_run, update_run_master_email_variants
from app.services.llm_gateway import generate_json
from app.services.outreach_email_pipeline import (
    build_template_fallback_meta,
    compose_outreach_subject_body,
)
from app.services.outreach_personalize import (
    MASTER_VARIANT_COUNT,
    normalize_variants_payload,
    personalize_outbound,
    select_variant_for_contact,
)
from app.services.prompt_builder import build_prompt
from app.services.run_context_service import get_prompt_setup_text

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
    logger.info("MASTER EMAIL run_id=%s variants=%s", run.id, len(variants))

    return {"variants": variants, "variant_count": len(variants), "generated": True}


def _variants_from_run(run) -> list[dict[str, str]]:
    vs = list(getattr(run, "master_email_variants", None) or [])
    if not vs:
        raise ValueError(
            "No master email variants. Complete generate_master_email_draft before generate_emails."
        )
    vs_sorted = sorted(vs, key=lambda x: x.position)
    return [{"subject": (x.subject or "").strip(), "body": (x.body or "").strip()} for x in vs_sorted]


def _outreach_email_payload_dict(
    contact: Contact,
    subject: str,
    body: str,
    generation_meta_json: dict | None = None,
) -> dict:
    row = {
        "contact_id": contact.id,
        "company": contact.company,
        "to": contact.email,
        "subject": subject,
        "body": body,
    }
    if generation_meta_json is not None:
        row["generation_meta_json"] = generation_meta_json
    return row


def _compose_outreach_email_payload_for_contact(
    db: Session,
    run,
    contact: Contact,
    variants: list[dict[str, str]] | None = None,
    *,
    variant_selection: str = "deterministic",
    regenerate_draft: EmailDraft | None = None,
) -> dict | None:
    """Build subject/body for one contact if sendable. No 'draft already exists' check.

    variant_selection:
      - "deterministic": same master variant per (run, contact) as initial generation.
      - "random": pick a random master variant (used on Regenerate so copy is not identical).
    """
    if contact.status != "valid":
        return None
    if contact.review_status not in {"approved", "edited"}:
        return None
    if not (contact.email or "").strip():
        return None

    prompt_saved = get_prompt_setup_text(run)
    if prompt_saved:
        try:
            subject, body, meta = compose_outreach_subject_body(
                db,
                run,
                contact,
                prompt_setup_text=prompt_saved,
                master_variant=None,
                regenerate_from_subject=regenerate_draft.subject if regenerate_draft else None,
                regenerate_from_body=regenerate_draft.body if regenerate_draft else None,
            )
            return _outreach_email_payload_dict(contact, subject, body, meta)
        except Exception as exc:
            logger.warning(
                "Prompt-setup outreach pipeline failed run_id=%s contact_id=%s: %s",
                run.id,
                contact.id,
                exc,
                exc_info=False,
            )

    if variants is None:
        if not list(getattr(run, "master_email_variants", None) or []):
            generate_master_email_draft(db, run.id, run.workflow_name, {})
            db.refresh(run)
        variants = _variants_from_run(run)

    if variant_selection == "random":
        variant = random.choice(variants)
        variant_idx = variants.index(variant)
    else:
        variant, variant_idx = select_variant_for_contact(run.id, contact.id, variants)
    logger.info(
        "EMAIL VARIANT run_id=%s contact_id=%s variant_idx=%s selection=%s",
        run.id,
        contact.id,
        variant_idx,
        variant_selection,
    )
    try:
        subject, body, meta = compose_outreach_subject_body(
            db,
            run,
            contact,
            prompt_setup_text=None,
            master_variant=variant,
        )
        return _outreach_email_payload_dict(contact, subject, body, meta)
    except Exception as exc:
        logger.warning(
            "Master-variant outreach pipeline failed run_id=%s contact_id=%s: %s — template fallback",
            run.id,
            contact.id,
            exc,
            exc_info=False,
        )

    subject, body = personalize_outbound(
        run.id,
        contact,
        variant["subject"],
        variant["body"],
    )
    meta = build_template_fallback_meta(db, run, contact, subject, body)
    return _outreach_email_payload_dict(contact, subject, body, meta)


def build_outreach_email_entry(
    db: Session,
    run,
    contact: Contact,
    variants: list[dict[str, str]] | None = None,
) -> dict | None:
    """One row for persist_generated_emails / generate_emails output; None if this contact should be skipped."""
    if find_draft_by_contact_id(db, run.id, contact.id):
        return None
    return _compose_outreach_email_payload_for_contact(db, run, contact, variants)


def generate_emails(db: Session, run_id: int, workflow_name: str, step_input: dict) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    sendable_contacts = list_sendable_contacts_by_run(db, run_id)

    prompt_saved = get_prompt_setup_text(run)
    variants: list[dict[str, str]] | None = None
    if not prompt_saved:
        if not list(getattr(run, "master_email_variants", None) or []):
            generate_master_email_draft(db, run_id, workflow_name, {})
            db.refresh(run)
        variants = _variants_from_run(run)

    emails: list[dict] = []
    for contact in sendable_contacts:
        entry = build_outreach_email_entry(db, run, contact, variants)
        if entry:
            emails.append(entry)

    return {
        "emails": emails,
        "email_count": len(emails),
    }


def materialize_outreach_draft_for_sendable_contact(
    db: Session,
    contact: Contact,
) -> EmailDraft | None:
    """
    If the contact is approved/edited, valid, has email, and workflow supports drafts:
    persist one personalized draft when missing — unified reasoning→draft pipeline (personalization_json);
    Prompt setup text or master variant as context; template personalize_outbound only as last resort.
    """
    from app.services.email_draft_persistence_service import persist_generated_emails
    from app.services.workflow_registry import WORKFLOWS

    if contact.review_status not in {"approved", "edited"}:
        return None
    if contact.status != "valid":
        return None
    if not (contact.email or "").strip():
        return None

    existing: EmailDraft | None = find_draft_by_contact_id(db, contact.run_id, contact.id)
    if existing:
        return existing

    run = get_run(db, contact.run_id)
    if not run:
        return None
    steps = WORKFLOWS.get(run.workflow_name)
    if not steps or "generate_emails" not in steps:
        return None

    entry = build_outreach_email_entry(db, run, contact)
    if not entry:
        return None
    persist_generated_emails(db, run.id, {"emails": [entry]})
    return find_draft_by_contact_id(db, contact.run_id, contact.id)


def ensure_outreach_draft_for_contact(db: Session, contact: Contact) -> None:
    """
    When a contact is approved or edited, create their personalized draft immediately
    (master variants are generated on first need). Safe to call multiple times.
    """
    try:
        materialize_outreach_draft_for_sendable_contact(db, contact)
    except Exception:
        logger.exception(
            "ensure_outreach_draft_for_contact failed run_id=%s contact_id=%s",
            contact.run_id,
            contact.id,
        )


def regenerate_outbound_email_draft(db: Session, draft_id: int) -> EmailDraft:
    """Rewrite subject/body on the same draft row so UI list order (by id) does not change."""
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError("Email draft not found")
    if draft.status in ("sent", "sending"):
        raise ValueError("Cannot regenerate sent or sending draft")

    contact = get_contact(db, draft.contact_id)
    if not contact:
        raise ValueError("Contact not found")
    run = get_run(db, draft.run_id)
    if not run:
        raise ValueError("Run not found")

    prompt_saved = get_prompt_setup_text(run)
    variants: list[dict[str, str]] | None = None
    if not prompt_saved:
        if not list(getattr(run, "master_email_variants", None) or []):
            generate_master_email_draft(db, run.id, run.workflow_name, {})
            db.refresh(run)
        variants = _variants_from_run(run)

    payload = _compose_outreach_email_payload_for_contact(
        db,
        run,
        contact,
        variants,
        variant_selection="random",
        regenerate_draft=draft,
    )
    if not payload:
        raise RuntimeError("Could not regenerate draft — approve the contact and ensure a valid email.")

    # Feature 1: re-sync the auto-attached program PDF to the NEW match (drop the stale one).
    # Must run before the new meta overwrites draft.matched_program_json.
    from app.services.email_draft_persistence_service import sync_matched_program_attachment
    sync_matched_program_attachment(db, draft, payload.get("generation_meta_json"))

    return update_email_draft_outreach_regenerate(
        db,
        draft,
        subject=payload["subject"],
        body=payload["body"],
        company=payload.get("company"),
        to_email=payload.get("to"),
        generation_meta_json=payload.get("generation_meta_json"),
    )
