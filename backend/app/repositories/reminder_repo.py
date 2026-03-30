from datetime import datetime

from sqlalchemy.orm import Session

from app.models.reminder import Reminder


def create_reminder(
    db: Session,
    run_id: int,
    title: str,
    remind_at,
    follow_up_task_id: int | None = None,
    thread_id: int | None = None,
    contact_id: int | None = None,
    description: str | None = None,
    status: str = "scheduled",
    priority: str = "medium",
    source_json: dict | None = None,
    output_json: dict | None = None,
) -> Reminder:
    reminder = Reminder(
        run_id=run_id,
        follow_up_task_id=follow_up_task_id,
        thread_id=thread_id,
        contact_id=contact_id,
        title=title,
        description=description,
        remind_at=remind_at,
        status=status,
        priority=priority,
        source_json=source_json or {},
        output_json=output_json or {},
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def get_reminder(db: Session, reminder_id: int) -> Reminder | None:
    return db.query(Reminder).filter(Reminder.id == reminder_id).first()


def list_reminders_by_run(db: Session, run_id: int) -> list[Reminder]:
    return (
        db.query(Reminder)
        .filter(Reminder.run_id == run_id)
        .order_by(Reminder.remind_at.asc(), Reminder.id.desc())
        .all()
    )


def list_reminders_by_follow_up_task(db: Session, follow_up_task_id: int) -> list[Reminder]:
    return (
        db.query(Reminder)
        .filter(Reminder.follow_up_task_id == follow_up_task_id)
        .order_by(Reminder.remind_at.asc(), Reminder.id.desc())
        .all()
    )


def find_active_reminder_for_follow_up_task(db: Session, follow_up_task_id: int) -> Reminder | None:
    return (
        db.query(Reminder)
        .filter(
            Reminder.follow_up_task_id == follow_up_task_id,
            Reminder.status.in_(["scheduled", "triggered", "snoozed"]),
        )
        .order_by(Reminder.id.desc())
        .first()
    )


def update_reminder_status(
    db: Session,
    reminder: Reminder,
    status: str,
    output_json: dict | None = None,
) -> Reminder:
    reminder.status = status
    if output_json is not None:
        reminder.output_json = output_json

    now = datetime.utcnow()

    if status == "triggered":
        reminder.triggered_at = now
    elif status == "completed":
        reminder.completed_at = now

    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


def snooze_reminder(
    db: Session,
    reminder: Reminder,
    remind_at,
    output_json: dict | None = None,
) -> Reminder:
    reminder.status = "snoozed"
    reminder.remind_at = remind_at
    if output_json is not None:
        reminder.output_json = output_json
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder
