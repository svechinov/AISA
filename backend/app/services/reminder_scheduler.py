from datetime import datetime

from sqlalchemy.orm import Session

from app.models.reminder import Reminder
from app.repositories.reminder_repo import update_reminder_status


def trigger_due_reminders(db: Session) -> dict:
    now = datetime.utcnow()

    due_reminders = (
        db.query(Reminder)
        .filter(
            Reminder.status.in_(["scheduled", "snoozed"]),
            Reminder.remind_at <= now,
        )
        .order_by(Reminder.remind_at.asc())
        .all()
    )

    triggered_ids = []

    for reminder in due_reminders:
        update_reminder_status(
            db=db,
            reminder=reminder,
            status="triggered",
            output_json={
                **(reminder.output_json or {}),
                "triggered_by": "manual_scheduler",
            },
        )
        triggered_ids.append(reminder.id)

    return {
        "due_found": len(due_reminders),
        "triggered": len(triggered_ids),
        "triggered_ids": triggered_ids,
    }
