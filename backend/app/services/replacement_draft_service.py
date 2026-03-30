import logging

from sqlalchemy.orm import Session

from app.repositories.contact_repo import list_approved_replacement_contacts_by_run
from app.repositories.email_draft_repo import create_email_draft, find_draft_by_contact_id
from app.repositories.run_repo import get_run, get_run_master_email_parts
from app.repositories.template_repo import get_template_by_type
from app.services.outreach_personalize import (
    normalize_variants_payload,
    personalize_outbound,
    select_variant_for_contact,
)
from app.services.template_renderer import personalize_outreach_text

logger = logging.getLogger(__name__)

DEFAULT_SUBJECT_TEMPLATE = "Note for {{company}}"

DEFAULT_BODY_TEMPLATE = """Hi {{name}},

We're reaching out regarding a matter that may be relevant to {{company}}.

Best regards"""


def generate_replacement_drafts(db: Session, run_id: int) -> dict:
    run = get_run(db, run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    replacement_contacts = list_approved_replacement_contacts_by_run(db, run_id)

    me = getattr(run, "master_email", None) or {}
    variants: list[dict[str, str]] | None = None
    try:
        if isinstance(me, dict):
            variants = normalize_variants_payload(me)
    except (ValueError, TypeError):
        variants = None

    subject_template_content: str | None = None
    body_template_content: str | None = None
    if variants is None:
        master_sub, master_body = get_run_master_email_parts(run)
        if master_sub and master_body:
            subject_template_content = master_sub
            body_template_content = master_body
        else:
            subject_template = get_template_by_type(
                db,
                template_type="outreach_subject",
                project_id=run.project_id,
            )
            body_template = get_template_by_type(
                db,
                template_type="outreach_body",
                project_id=run.project_id,
            )
            subject_template_content = subject_template.content if subject_template else DEFAULT_SUBJECT_TEMPLATE
            body_template_content = body_template.content if body_template else DEFAULT_BODY_TEMPLATE

    created_rows = []
    skipped_contact_ids: list[int] = []

    for contact in replacement_contacts:
        existing_draft = find_draft_by_contact_id(db, run_id, contact.id)
        if existing_draft:
            skipped_contact_ids.append(contact.id)
            continue

        if variants is not None:
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
        else:
            variables = {
                "company": contact.company or "",
                "website": contact.website or "",
                "name": contact.name or "",
                "role": contact.role or "",
                "email": contact.email or "",
            }
            subject = personalize_outreach_text(subject_template_content or "", variables).strip()
            body = personalize_outreach_text(body_template_content or "", variables).strip()

        draft = create_email_draft(
            db=db,
            run_id=run_id,
            contact_id=contact.id,
            company=contact.company,
            to_email=contact.email,
            subject=subject,
            body=body,
            status="draft",
            review_status="pending",
            review_notes=None,
        )

        created_rows.append(
            {
                "draft_id": draft.id,
                "contact_id": contact.id,
                "company": contact.company,
                "to_email": contact.email,
            }
        )

    return {
        "run_id": run_id,
        "replacement_contacts_found": len(replacement_contacts),
        "drafts_created": len(created_rows),
        "created": created_rows,
        "skipped_existing_draft_contact_ids": skipped_contact_ids,
    }
