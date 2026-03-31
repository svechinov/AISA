"""Computed run phase and dashboard fields for human UI (run-centered)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.contact_repo import list_contacts_by_run
from app.repositories.reminder_repo import list_reminders_by_run
from app.repositories.step_repo import get_step_by_run_and_name, list_steps_by_run
from app.repositories.email_thread_repo import list_email_threads_by_run
from app.services.run_summary_service import get_run_summary

# Still approved/edited in DB, but not counted as “ready contacts” in setup summary.
_UNDELIVERABLE_EMAIL_HEALTH = frozenset({"bounced", "dead_mailbox"})


def _count_contacts_approved_reachable(db: Session, run_id: int) -> int:
    """Approved or edited contacts that are not bounced / dead mailbox."""
    contacts = list_contacts_by_run(db, run_id)
    return sum(
        1
        for c in contacts
        if c.review_status in {"approved", "edited"}
        and (c.email_health or "unknown") not in _UNDELIVERABLE_EMAIL_HEALTH
    )


def _count_companies_from_step(db: Session, run_id: int) -> int | None:
    st = get_step_by_run_and_name(db, run_id, "collect_companies")
    if not st or st.status != "completed":
        return None
    out = st.output_json or {}
    companies = out.get("companies")
    if not isinstance(companies, list):
        return 0
    return len(companies)


def _count_contacts_from_find_step(db: Session, run_id: int) -> int | None:
    st = get_step_by_run_and_name(db, run_id, "find_contacts")
    if not st or st.status != "completed":
        return None
    out = st.output_json or {}
    contacts = out.get("contacts")
    if not isinstance(contacts, list):
        return 0
    return len(contacts)


def _count_validated_from_step(db: Session, run_id: int) -> int | None:
    """Count contacts that passed through validate_contacts (from step output when completed)."""
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st or st.status != "completed":
        return None
    out = st.output_json or {}
    valid = out.get("valid_contacts")
    invalid = out.get("invalid_contacts")
    if not isinstance(valid, list) or not isinstance(invalid, list):
        return None
    return len(valid) + len(invalid)


def _reminder_due_and_active_counts(reminders: list, now: datetime) -> tuple[int, int]:
    """Due = scheduled/snoozed with remind_at <= now. Active = scheduled, triggered, or snoozed."""
    due = sum(
        1
        for r in reminders
        if r.status in ("scheduled", "snoozed") and r.remind_at and r.remind_at <= now
    )
    active = sum(1 for r in reminders if r.status in ("scheduled", "triggered", "snoozed"))
    return due, active


def get_run_setup_summary(db: Session, run_id: int) -> dict:
    """Counts for Run setup card (null = step not finished yet — hide row in UI)."""
    summary = get_run_summary(db, run_id)
    companies = _count_companies_from_step(db, run_id)
    contacts_found_step = _count_contacts_from_find_step(db, run_id)
    contacts_found = (
        contacts_found_step if contacts_found_step is not None else summary["contacts_found"]
    )
    validated_step = _count_validated_from_step(db, run_id)
    contacts_validated = (
        validated_step
        if validated_step is not None
        else summary["valid_contacts"] + summary["invalid_contacts"]
    )
    return {
        "companies_collected": companies,
        "contacts_found": contacts_found,
        "contacts_validated": contacts_validated,
        "contacts_approved": _count_contacts_approved_reachable(db, run_id),
    }


def get_run_display_phase(db: Session, run) -> str:
    """Preparing | Ready | Active | Closed (exact UI labels)."""
    if run.closed_at is not None:
        return "Closed"
    summary = get_run_summary(db, run.id)
    if summary["drafts_sent"] > 0 or summary["events_sent"] > 0:
        return "Active"
    if run.status == "drafts_ready":
        return "Ready"
    return "Preparing"


def get_conversations_snapshot(db: Session, run_id: int) -> dict:
    summary = get_run_summary(db, run_id)
    threads = list_email_threads_by_run(db, run_id)
    active_threads = len([t for t in threads if (t.status or "").lower() == "open"])
    reminders = list_reminders_by_run(db, run_id)
    now = datetime.utcnow()
    reminders_due, reminders_active = _reminder_due_and_active_counts(reminders, now)
    return {
        "active_threads": active_threads,
        "replies_received": summary["events_replied"],
        "reply_drafts": summary["reply_drafts_generated"],
        "reminders_active": reminders_active,
        "reminders_due": reminders_due,
    }


def get_run_performance_rows(db: Session, run_id: int) -> dict:
    """Counters for Run performance card; omit keys with no data yet where appropriate."""
    summary = get_run_summary(db, run_id)
    threads = list_email_threads_by_run(db, run_id)
    active_threads = len([t for t in threads if (t.status or "").lower() == "open"])
    reminders = list_reminders_by_run(db, run_id)
    now = datetime.utcnow()
    reminders_due, reminders_active = _reminder_due_and_active_counts(reminders, now)

    return {
        "emails_sent": summary["drafts_sent"],
        "replies": summary["events_replied"],
        "active_threads": active_threads,
        "interested": summary["threads_interested"],
        "need_more_info": summary["threads_need_info"],
        "packets_sent": summary["asset_packets_sent"],
        "reminders_active": reminders_active,
        "reminders_due": reminders_due,
    }


def setup_steps_for_run(db: Session, run_id: int) -> list[dict]:
    """Three setup steps with retry_count and UI status badge."""
    names = ["collect_companies", "find_contacts", "validate_contacts"]
    titles = ["Collect companies", "Find contacts", "Validate contacts"]
    out = []
    for title, name in zip(titles, names, strict=True):
        step = get_step_by_run_and_name(db, run_id, name)
        if not step:
            ui_status = "Not started"
            retry = 0
        elif step.status == "completed":
            ui_status = "Completed"
            retry = step.retry_count or 0
        elif step.status in ("running", "failed"):
            ui_status = "In progress"
            retry = step.retry_count or 0
        else:
            ui_status = "Not started"
            retry = step.retry_count or 0
        out.append(
            {
                "step_name": name,
                "title": title,
                "retry_count": retry,
                "ui_status": ui_status,
            },
        )
    return out


def get_setup_state_message(db: Session, run) -> str:
    phase = get_run_display_phase(db, run)
    if phase == "Ready":
        return "This run is ready for outreach"
    if phase in ("Active", "Closed"):
        return "Run setup is complete"
    return "Run setup is in progress"


def enrich_run_for_card(db: Session, run) -> dict:
    summary = get_run_summary(db, run.id)
    threads = list_email_threads_by_run(db, run.id)
    active_threads = len([t for t in threads if (t.status or "").lower() == "open"])
    companies = _count_companies_from_step(db, run.id)
    step_find = get_step_by_run_and_name(db, run.id, "find_contacts")
    contacts_found = (
        len(step_find.output_json.get("contacts") or [])
        if step_find and step_find.status == "completed" and isinstance(step_find.output_json, dict)
        else summary["contacts_found"]
    )

    updated_at = run.created_at
    for s in list_steps_by_run(db, run.id):
        if s.finished_at and (updated_at is None or s.finished_at > updated_at):
            updated_at = s.finished_at

    name = run.name or f"Run #{run.id}"
    return {
        "id": run.id,
        "project_id": run.project_id,
        "name": name,
        "notes": run.notes,
        "segment": run.segment,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "display_phase": get_run_display_phase(db, run),
        "closed_at": run.closed_at,
        "companies_count": companies if companies is not None else 0,
        "contacts_count": contacts_found,
        "emails_sent": summary["drafts_sent"],
        "replies": summary["events_replied"],
        "active_threads": active_threads,
        "updated_at": updated_at,
        "created_at": run.created_at,
    }


