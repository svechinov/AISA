from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.suppression_entry import REASON_UNSUBSCRIBE
from app.repositories.contact_repo import get_contact
from app.repositories.email_thread_repo import get_email_thread
from app.repositories.follow_up_task_repo import (
    create_follow_up_task,
    find_open_follow_up_task_by_thread_and_type,
)

# B-138: not_interested is a cooldown, not a permanent ban — decision 20.07, a studio's open roles
# look different in 6 months. unsubscribe stays permanent (see REASON_UNSUBSCRIBE branch below).
NOT_INTERESTED_SUPPRESSION_COOLDOWN_DAYS = 183


def create_next_action_for_thread(db: Session, thread_id: int) -> dict:
    thread = get_email_thread(db, thread_id)
    if not thread:
        raise ValueError(f"Thread {thread_id} not found")

    contact = get_contact(db, thread.contact_id)
    if not contact:
        raise ValueError(f"Contact {thread.contact_id} not found")

    classification = thread.classification
    if not classification:
        raise ValueError("Thread has no classification")

    if classification == "interested":
        task_type = "reply_to_interested"
        title = f"Reply to interested lead: {contact.company or 'Unknown company'}"
        description = "Prepare or review a reply for an interested contact."
        priority = "high"
        due_at = datetime.utcnow() + timedelta(days=1)

    elif classification == "need_more_info":
        task_type = "send_more_info"
        title = f"Send more information: {contact.company or 'Unknown company'}"
        description = "Prepare and send additional materials requested by the contact."
        priority = "high"
        due_at = datetime.utcnow() + timedelta(days=1)

    elif classification == "ask_later":
        task_type = "follow_up_later"
        title = f"Follow up later: {contact.company or 'Unknown company'}"
        description = "Contact asked to revisit later."
        priority = "medium"
        due_at = datetime.utcnow() + timedelta(days=14)

    elif classification == "not_interested":
        task_type = "close_thread"
        title = f"Close thread: {contact.company or 'Unknown company'}"
        description = "Mark thread as not interested and close it."
        priority = "low"
        due_at = None
        # Cross-run do-not-contact, but only for 6 months (B-138) — never email a contact who
        # declined, from any run, until the cooldown expires.
        try:
            from app.repositories.suppression_repo import add_suppression

            add_suppression(
                db, contact.email, reason="not_interested",
                source_run_id=thread.run_id, note="reply classified not_interested",
                expires_at=datetime.utcnow() + timedelta(days=NOT_INTERESTED_SUPPRESSION_COOLDOWN_DAYS),
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception("suppress not_interested contact %s failed", contact.id)

    elif classification == "unsubscribe":
        task_type = "unsubscribe"
        title = f"Unsubscribed: {contact.company or 'Unknown company'}"
        description = "Contact opted out by reply — added to suppression list, cadence stopped."
        priority = "low"
        due_at = None
        # CAN-SPAM (B-128 Phase 1b): reply-based opt-out is cross-run do-not-contact, same as
        # not_interested; contactability.py already gates both send and follow-up for anyone here.
        try:
            from app.repositories.suppression_repo import add_suppression

            add_suppression(
                db, contact.email, reason=REASON_UNSUBSCRIBE,
                source_run_id=thread.run_id, note="reply classified unsubscribe",
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception("suppress unsubscribe contact %s failed", contact.id)

    else:
        raise ValueError(f"Unsupported classification for next action: {classification}")

    existing = find_open_follow_up_task_by_thread_and_type(db, thread.id, task_type)
    if existing:
        return {
            "thread_id": thread.id,
            "task_id": existing.id,
            "deduplicated": True,
            "task_type": task_type,
        }

    task = create_follow_up_task(
        db=db,
        run_id=thread.run_id,
        thread_id=thread.id,
        contact_id=thread.contact_id,
        task_type=task_type,
        title=title,
        description=description,
        priority=priority,
        due_at=due_at,
        status="open",
        source_json={
            "classification": classification,
            "thread_id": thread.id,
        },
        output_json={},
    )

    return {
        "thread_id": thread.id,
        "task_id": task.id,
        "deduplicated": False,
        "task_type": task_type,
    }
