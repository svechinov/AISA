from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories.contact_repo import get_contact
from app.repositories.email_thread_repo import get_email_thread
from app.repositories.follow_up_task_repo import (
    create_follow_up_task,
    find_open_follow_up_task_by_thread_and_type,
)


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
