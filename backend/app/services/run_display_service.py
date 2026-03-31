"""Computed run phase and dashboard fields for human UI (run-centered)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.contact_repo import list_contacts_by_run
from app.repositories.reminder_repo import list_reminders_by_run
from app.repositories.step_repo import get_step_by_run_and_name, list_steps_by_run
from app.repositories.email_thread_repo import list_email_threads_by_run
from app.repositories.run_repo import get_run
from app.services.run_companies_status_service import _norm, _strip_url
from app.services.run_summary_service import get_run_summary
from app.setup_milestones import (
    SETUP_MILESTONE_COMPANIES,
    SETUP_MILESTONE_CONTACTS,
    SETUP_MILESTONE_VALID_CONTACTS,
)

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


def _live_company_count(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "collect_companies")
    if not st:
        return 0
    companies = (st.output_json or {}).get("companies")
    return len(companies) if isinstance(companies, list) else 0


def _live_contact_count(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "find_contacts")
    if not st:
        return 0
    contacts = (st.output_json or {}).get("contacts")
    return len(contacts) if isinstance(contacts, list) else 0


def _canonical_company_key_from_contact_row(c: dict) -> str | None:
    """Stable key for counting distinct companies on contact dicts (find_contacts output)."""
    if not isinstance(c, dict):
        return None
    co = _norm(c.get("company") or "")
    w = _strip_url(c.get("website") or "")
    if not co and not w:
        return None
    return f"{co}\x1f{w}"


def _live_distinct_companies_in_find_contacts(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "find_contacts")
    if not st:
        return 0
    contacts = (st.output_json or {}).get("contacts")
    if not isinstance(contacts, list):
        return 0
    keys = {k for c in contacts if (k := _canonical_company_key_from_contact_row(c)) is not None}
    return len(keys)


def _live_valid_contact_count(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st:
        return 0
    v = (st.output_json or {}).get("valid_contacts")
    return len(v) if isinstance(v, list) else 0


def _live_validated_total_count(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if st and isinstance(st.output_json, dict):
        v = st.output_json.get("valid_contacts")
        i = st.output_json.get("invalid_contacts")
        if isinstance(v, list) and isinstance(i, list):
            return len(v) + len(i)
    summary = get_run_summary(db, run_id)
    return summary["valid_contacts"] + summary["invalid_contacts"]


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
    """Live counts from step output_json (works while status is running) plus DB fallbacks."""
    summary = get_run_summary(db, run_id)
    n_co = _live_company_count(db, run_id)
    n_fi = _live_contact_count(db, run_id)
    contacts_found = max(n_fi, summary["contacts_found"])
    contacts_validated = max(
        _live_validated_total_count(db, run_id),
        summary["valid_contacts"] + summary["invalid_contacts"],
    )
    contacts_found_distinct_companies = _live_distinct_companies_in_find_contacts(db, run_id)
    return {
        "companies_collected": n_co,
        "contacts_found": contacts_found,
        "contacts_found_distinct_companies": contacts_found_distinct_companies,
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
    """Setup steps: 'Completed' only when numeric milestones are met (not raw step.status)."""
    run = get_run(db, run_id)
    if not run:
        return []

    n_co = _live_company_count(db, run_id)
    n_fi = _live_contact_count(db, run_id)
    n_va = _live_valid_contact_count(db, run_id)

    names = ["collect_companies", "find_contacts", "validate_contacts"]
    titles = ["Collect companies", "Find contacts", "Validate contacts"]
    out = []
    for title, name in zip(titles, names, strict=True):
        step = get_step_by_run_and_name(db, run_id, name)
        retry = step.retry_count if step else 0

        if name == "collect_companies":
            milestone_done = n_co >= SETUP_MILESTONE_COMPANIES
        elif name == "find_contacts":
            milestone_done = n_co >= SETUP_MILESTONE_COMPANIES and n_fi >= SETUP_MILESTONE_CONTACTS
        else:
            milestone_done = (
                n_co >= SETUP_MILESTONE_COMPANIES
                and n_fi >= SETUP_MILESTONE_CONTACTS
                and n_va >= SETUP_MILESTONE_VALID_CONTACTS
            )

        if milestone_done:
            ui_status = "Completed"
        elif run.status == "pending":
            ui_status = "Not started"
        else:
            ui_status = "In progress"

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
    companies = _live_company_count(db, run.id)
    contacts_found = max(_live_contact_count(db, run.id), summary["contacts_found"])

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
        "companies_count": companies,
        "contacts_count": contacts_found,
        "emails_sent": summary["drafts_sent"],
        "replies": summary["events_replied"],
        "active_threads": active_threads,
        "updated_at": updated_at,
        "created_at": run.created_at,
    }


