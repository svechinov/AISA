from sqlalchemy.orm import Session

from app.models.reply_draft import ReplyDraft
from app.repositories.contact_repo import get_contact
from app.repositories.email_message_repo import list_email_messages_by_thread
from app.repositories.email_thread_repo import get_email_thread
from app.repositories.reply_draft_repo import (
    create_reply_draft,
    find_reply_draft_by_thread_and_type,
    get_reply_draft,
)
from app.repositories.run_repo import get_run
from app.repositories.template_repo import get_template_by_type
from app.services.template_renderer import render_template

DEFAULT_NEED_INFO_SUBJECT = "Re: {{thread_subject}}"

# Neutral fallbacks used only when no reply templates are seeded for the project.
# Keep them industry-agnostic and unsigned: the campaign persona/signature comes from
# run_setup (sender_signature_html) and seeded templates, never from hardcoded defaults.
DEFAULT_NEED_INFO_BODY = """Hi {{name}},

Thanks for your reply.

Happy to share more details about how we could help {{company}} — I can send a short overview or answer specific questions, whichever is easier.

What would be most useful for you?"""

DEFAULT_INTERESTED_SUBJECT = "Re: {{thread_subject}}"

DEFAULT_INTERESTED_BODY = """Hi {{name}},

Great to hear from you.

Happy to discuss next steps — would a short 15-minute call this week work? I can also send more details by email first if you prefer."""


def _build_reply_subject_body_for_thread(db: Session, thread) -> tuple[str, str]:
    """Shared template render for create + regenerate."""
    run = get_run(db, thread.run_id)
    if not run:
        raise ValueError(f"Run {thread.run_id} not found")

    contact = get_contact(db, thread.contact_id)
    if not contact:
        raise ValueError(f"Contact {thread.contact_id} not found")

    messages = list_email_messages_by_thread(db, thread.id)
    last_inbound = None
    for message in reversed(messages):
        if message.direction == "inbound":
            last_inbound = message
            break

    reply_type = thread.classification

    if reply_type == "need_more_info":
        subject_template = get_template_by_type(
            db, "reply_need_more_info_subject", project_id=run.project_id
        )
        body_template = get_template_by_type(
            db, "reply_need_more_info_body", project_id=run.project_id
        )
        subject_content = subject_template.content if subject_template else DEFAULT_NEED_INFO_SUBJECT
        body_content = body_template.content if body_template else DEFAULT_NEED_INFO_BODY
    else:
        subject_template = get_template_by_type(
            db, "reply_interested_subject", project_id=run.project_id
        )
        body_template = get_template_by_type(
            db, "reply_interested_body", project_id=run.project_id
        )
        subject_content = subject_template.content if subject_template else DEFAULT_INTERESTED_SUBJECT
        body_content = body_template.content if body_template else DEFAULT_INTERESTED_BODY

    variables = {
        "name": contact.name or "",
        "company": contact.company or "",
        "role": contact.role or "",
        "email": contact.email or "",
        "thread_subject": thread.subject or "",
        "last_inbound_body": last_inbound.body if last_inbound else "",
    }

    subject = render_template(subject_content, variables).strip()
    body = render_template(body_content, variables).strip()
    return subject, body


def regenerate_reply_draft(db: Session, draft_id: int) -> ReplyDraft:
    """Re-render subject/body from templates; reset review to pending (new version of the reply)."""
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise ValueError("Reply draft not found")
    if draft.status in ("sent", "sending"):
        raise ValueError("Cannot regenerate a sent or sending reply draft")

    thread = get_email_thread(db, draft.thread_id)
    if not thread:
        raise ValueError("Thread not found")

    subject, body = _build_reply_subject_body_for_thread(db, thread)
    draft.subject = subject
    draft.body = body
    draft.review_status = "pending"
    draft.review_notes = None
    draft.reviewed_at = None
    draft.status = "draft"
    draft.error_message = None

    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def generate_reply_draft_for_thread(db: Session, thread_id: int) -> dict:
    thread = get_email_thread(db, thread_id)
    if not thread:
        raise ValueError(f"Thread {thread_id} not found")

    if thread.classification not in {"need_more_info", "interested"}:
        raise ValueError("Reply draft generation is only supported for need_more_info or interested")

    existing = find_reply_draft_by_thread_and_type(db, thread_id, thread.classification)
    if existing:
        return {
            "thread_id": thread.id,
            "reply_type": thread.classification,
            "reply_draft_id": existing.id,
            "deduplicated": True,
        }

    reply_type = thread.classification
    contact = get_contact(db, thread.contact_id)
    if not contact:
        raise ValueError(f"Contact {thread.contact_id} not found")

    subject, body = _build_reply_subject_body_for_thread(db, thread)

    draft = create_reply_draft(
        db=db,
        run_id=thread.run_id,
        thread_id=thread.id,
        contact_id=thread.contact_id,
        reply_type=reply_type,
        to_email=contact.email,
        subject=subject,
        body=body,
        status="draft",
        review_status="pending",
        review_notes=None,
    )

    return {
        "thread_id": thread.id,
        "reply_type": reply_type,
        "reply_draft_id": draft.id,
        "deduplicated": False,
    }
