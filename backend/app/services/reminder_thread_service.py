from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories.contact_repo import get_contact
from app.repositories.email_thread_repo import get_email_thread
from app.repositories.reminder_repo import (
    create_reminder,
    find_active_reminder_for_thread,
)


def create_reminder_for_thread(
    db: Session,
    thread_id: int,
    remind_at: datetime | None = None,
) -> dict:
    thread = get_email_thread(db, thread_id)
    if not thread:
        raise ValueError(f"Thread {thread_id} not found")

    existing = find_active_reminder_for_thread(db, thread.id)
    if existing:
        return {
            "thread_id": thread.id,
            "reminder_id": existing.id,
            "deduplicated": True,
        }

    contact = get_contact(db, thread.contact_id)
    company = (contact.company or "").strip() if contact else ""
    subject = (thread.subject or "").strip() or "Thread"
    title = f"Remind later: {company or subject}"[:255]
    description = f"Thread #{thread.id}: {subject}"

    effective = remind_at or (datetime.utcnow() + timedelta(days=3))

    reminder = create_reminder(
        db=db,
        run_id=thread.run_id,
        follow_up_task_id=None,
        thread_id=thread.id,
        contact_id=thread.contact_id,
        title=title,
        description=description,
        remind_at=effective,
        status="scheduled",
        priority="medium",
        source_json={
            "source": "thread",
            "thread_id": thread.id,
        },
        output_json={},
    )

    return {
        "thread_id": thread.id,
        "reminder_id": reminder.id,
        "deduplicated": False,
    }
