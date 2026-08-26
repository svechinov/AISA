import logging

from sqlalchemy.orm import Session

from app.models.email_thread import EmailThread
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
from app.services.follow_up_service import create_next_action_for_thread
from app.services.reply_classifier import classify_reply

_log = logging.getLogger(__name__)


def apply_reply_classification(
    db: Session,
    thread: EmailThread,
    body: str,
    *,
    create_task: bool,
) -> dict:
    """
    B-138: single code path for classifying one inbound reply and persisting it onto the thread.
    Used by both the real Gmail sync (gmail_tracking_sync_service) and the mock/dev endpoint below
    — one code path for both, so suppression/follow-up consequences never diverge between them.

    create_task=True also drives follow_up_service.create_next_action_for_thread(), which creates
    the follow-up task AND adds cross-run suppression for not_interested/unsubscribe (dedup on
    thread+task_type is built in there). Re-classifying an already-classified thread is intentional
    — the dialogue can move on and there is no manual override of the class in this system, so the
    latest inbound message wins.

    create_task=False skips that call entirely — used to preserve the mock endpoint's historical
    behavior (it never created follow-up tasks/suppression; see receive_mock_reply below).

    classify_reply() strips quoted history first and returns None when nothing of the new reply
    is left after stripping (B-138) — in that case this is a no-op, not a guess: the thread keeps
    whatever classification it already had.
    """
    classification = classify_reply(body)
    if classification is None:
        return {
            "thread_id": thread.id,
            "classification": thread.classification,
            "classification_confidence": thread.classification_confidence,
            "classification_reason": thread.classification_reason,
            "next_action": None,
        }
    thread.classification = classification["label"]
    thread.classification_confidence = classification["confidence"]
    thread.classification_reason = classification["reason"]
    db.add(thread)
    db.commit()
    db.refresh(thread)

    next_action = None
    if create_task:
        try:
            next_action = create_next_action_for_thread(db, thread.id)
        except ValueError:
            # e.g. "unclear" has no next-action recipe in follow_up_service — not an error, just
            # nothing to do for this class.
            _log.debug(
                "no next action for thread=%s classification=%s", thread.id, thread.classification,
            )

    return {
        "thread_id": thread.id,
        "classification": thread.classification,
        "classification_confidence": thread.classification_confidence,
        "classification_reason": thread.classification_reason,
        "next_action": next_action,
    }


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

    # B-138: create_task=False preserves this endpoint's historical behavior — it never created
    # follow-up tasks/suppression, only classified. Kept deliberately, not changed silently.
    apply_reply_classification(db, thread, body, create_task=False)

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
