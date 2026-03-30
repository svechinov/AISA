from sqlalchemy.orm import Session

from app.repositories.contact_repo import get_contact, mark_contact_replied
from app.repositories.email_draft_repo import get_email_draft, mark_email_draft_replied
from app.repositories.email_event_repo import create_email_event
from app.repositories.email_message_repo import create_email_message
from app.repositories.email_thread_repo import (
    find_email_thread_by_provider_thread_id,
    get_email_thread_by_draft_id,
    touch_email_thread,
    update_email_thread_status,
)
from app.services.reply_classifier import classify_reply


def receive_mock_reply(
    db: Session,
    draft_id: int,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    provider_message_id: str | None = None,
) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    thread = None
    if draft.thread_id:
        thread = find_email_thread_by_provider_thread_id(db, draft.thread_id)
    if thread is None:
        thread = get_email_thread_by_draft_id(db, draft.id)

    if not thread:
        raise ValueError(f"No thread found for draft {draft.id}; send the draft first.")

    create_email_message(
        db=db,
        thread_id=thread.id,
        run_id=draft.run_id,
        contact_id=draft.contact_id,
        draft_id=draft.id,
        direction="inbound",
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        body=body,
        provider_message_id=provider_message_id,
    )

    classification = classify_reply(body)
    thread.classification = classification["label"]
    thread.classification_confidence = classification["confidence"]
    thread.classification_reason = classification["reason"]
    db.add(thread)
    db.commit()
    db.refresh(thread)

    update_email_thread_status(db, thread, "replied")
    touch_email_thread(db, thread)
    mark_email_draft_replied(db, draft)

    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_replied(db, contact)

    create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="replied",
        provider_message_id=provider_message_id,
        payload_json={
            "from_email": from_email,
            "to_email": to_email,
            "subject": subject,
        },
    )

    return {
        "draft_id": draft.id,
        "thread_id": thread.id,
        "contact_id": contact.id if contact else None,
        "status": "replied",
        "classification": thread.classification,
        "classification_confidence": thread.classification_confidence,
        "classification_reason": thread.classification_reason,
    }
