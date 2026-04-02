"""Computed run phase and dashboard fields for human UI (run-centered)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_event import EmailEvent
from app.models.reply_draft import ReplyDraft
from app.models.email_thread import EmailThread
from app.repositories.contact_repo import list_contacts_by_run
from app.repositories.email_draft_repo import list_email_drafts_by_run
from app.repositories.reminder_repo import list_reminders_by_run
from app.repositories.step_repo import get_step_by_run_and_name, list_steps_by_run
from app.repositories.email_thread_repo import (
    list_email_threads_by_run,
    resolve_thread_outbound_draft_id,
)
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

_PROMPT_SETUP_KEY = "prompt_setup_text"


def prompt_setup_saved_from_context(context_json: dict | None) -> bool:
    if not context_json:
        return False
    raw = context_json.get(_PROMPT_SETUP_KEY)
    return isinstance(raw, str) and len(raw.strip()) > 0


def signature_html_has_meaningful_content(html: str | None) -> bool:
    """Match Human UI `runSignatureHasMeaningfulContent`: strip tags/styles, require non-empty text."""
    raw = (html or "").strip()
    if not raw:
        return False
    text = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).replace("\u00a0", " ").strip()
    return len(text) > 0


def count_emails_sent_in_last_hours(db: Session, run_id: int, *, hours: int = 24) -> int:
    """Outreach + reply drafts actually sent with ``sent_at`` in the last ``hours`` (UTC)."""
    if hours < 1:
        return 0
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    n_out = (
        db.query(func.count())
        .select_from(EmailDraft)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.status == "sent",
            EmailDraft.sent_at.isnot(None),
            EmailDraft.sent_at >= cutoff,
        )
        .scalar()
    )
    n_reply = (
        db.query(func.count())
        .select_from(ReplyDraft)
        .filter(
            ReplyDraft.run_id == run_id,
            ReplyDraft.status == "sent",
            ReplyDraft.sent_at.isnot(None),
            ReplyDraft.sent_at >= cutoff,
        )
        .scalar()
    )
    return int(n_out or 0) + int(n_reply or 0)


def hourly_send_counts_24h_utc(db: Session, run_id: int) -> list[int]:
    """Outreach + reply sends per hour over the last 24 hours (UTC).

    ``buckets[0]`` = hour starting at (now_utc - 24h), ``buckets[23]`` = hour ending at now_utc.
    """
    now = datetime.utcnow()
    start = now - timedelta(hours=24)
    buckets = [0] * 24

    def bump(st: datetime | None) -> None:
        if st is None or st < start or st > now:
            return
        sec = (st - start).total_seconds()
        if sec < 0:
            return
        idx = int(sec // 3600)
        if idx >= 24:
            idx = 23
        if idx < 0:
            return
        buckets[idx] += 1

    for st in (
        db.query(EmailDraft.sent_at)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.status == "sent",
            EmailDraft.sent_at.isnot(None),
            EmailDraft.sent_at >= start,
            EmailDraft.sent_at <= now,
        )
        .all()
    ):
        bump(st[0])

    for st in (
        db.query(ReplyDraft.sent_at)
        .filter(
            ReplyDraft.run_id == run_id,
            ReplyDraft.status == "sent",
            ReplyDraft.sent_at.isnot(None),
            ReplyDraft.sent_at >= start,
            ReplyDraft.sent_at <= now,
        )
        .all()
    ):
        bump(st[0])

    return buckets


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


def _canonical_company_key_from_orm_contact(c) -> str | None:
    co = _norm(c.company or "")
    w = _strip_url(c.website or "")
    if not co and not w:
        return None
    return f"{co}\x1f{w}"


def _live_valid_contact_count(db: Session, run_id: int) -> int:
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st:
        return 0
    v = (st.output_json or {}).get("valid_contacts")
    return len(v) if isinstance(v, list) else 0


def _contact_row_has_email(row: dict) -> bool:
    return isinstance(row, dict) and bool(str(row.get("email") or "").strip())


def _live_validated_step_count_with_email(db: Session, run_id: int) -> int | None:
    """validate_contacts JSON lists — only rows with a non-empty email (no-email ≠ validated for summary)."""
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st or not isinstance(st.output_json, dict):
        return None
    v = st.output_json.get("valid_contacts")
    i = st.output_json.get("invalid_contacts")
    if not isinstance(v, list) or not isinstance(i, list):
        return None
    return (
        sum(1 for x in v if _contact_row_has_email(x))
        + sum(1 for x in i if _contact_row_has_email(x))
    )


def _count_db_contacts_valid_or_invalid_with_email(db: Session, run_id: int) -> int:
    contacts = list_contacts_by_run(db, run_id)
    return sum(
        1
        for c in contacts
        if c.status in ("valid", "invalid") and (c.email or "").strip()
    )


def _count_db_contacts_no_email(db: Session, run_id: int) -> int:
    contacts = list_contacts_by_run(db, run_id)
    return sum(1 for c in contacts if not (c.email or "").strip())


def _live_distinct_companies_validated_with_email_step(db: Session, run_id: int) -> int | None:
    """Distinct companies among valid+invalid rows in validate output that have an email."""
    st = get_step_by_run_and_name(db, run_id, "validate_contacts")
    if not st or not isinstance(st.output_json, dict):
        return None
    v = st.output_json.get("valid_contacts")
    i = st.output_json.get("invalid_contacts")
    if not isinstance(v, list) or not isinstance(i, list):
        return None
    keys: set[str] = set()
    for row in (*v, *i):
        if not isinstance(row, dict) or not _contact_row_has_email(row):
            continue
        if k := _canonical_company_key_from_contact_row(row):
            keys.add(k)
    return len(keys)


def _count_db_distinct_companies_validated_with_email(db: Session, run_id: int) -> int:
    contacts = list_contacts_by_run(db, run_id)
    keys: set[str] = set()
    for c in contacts:
        if c.status not in ("valid", "invalid") or not (c.email or "").strip():
            continue
        if k := _canonical_company_key_from_orm_contact(c):
            keys.add(k)
    return len(keys)


def _thread_is_bounced_or_dead_mailbox_row(
    db: Session,
    thread: EmailThread,
    contacts: dict[int, Contact],
    drafts: dict[int, EmailDraft],
) -> bool:
    """Matches Human UI Threads tab: bounced / dead mailbox from draft + contact.email_health."""
    contact = contacts.get(thread.contact_id)
    eff = resolve_thread_outbound_draft_id(db, thread)
    linked = drafts.get(int(eff)) if eff is not None else None

    if linked is not None:
        ts = (linked.tracking_status or "").strip().lower()
        st = (linked.status or "").strip().lower()
        draft_lifecycle = ts if ts else st
        if draft_lifecycle == "dead_mailbox":
            return True
        if ts == "bounced":
            return True

    if contact is not None:
        eh = (contact.email_health or "").strip().lower()
        if eh == "dead_mailbox":
            return True
        if eh == "bounced":
            return True
    return False


def _active_threads_count_for_performance(db: Session, run_id: int) -> int:
    """Threads not in Bounced / Dead mailbox buckets (same as TrackingView threadBucketCounts.active)."""
    threads = list_email_threads_by_run(db, run_id)
    contacts = {c.id: c for c in list_contacts_by_run(db, run_id)}
    drafts = {d.id: d for d in list_email_drafts_by_run(db, run_id)}
    return sum(
        1
        for t in threads
        if not _thread_is_bounced_or_dead_mailbox_row(db, t, contacts, drafts)
    )


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
    step_validated_with_email = _live_validated_step_count_with_email(db, run_id)
    db_validated_with_email = _count_db_contacts_valid_or_invalid_with_email(db, run_id)
    contacts_validated = max(step_validated_with_email or 0, db_validated_with_email)
    step_v_dc = _live_distinct_companies_validated_with_email_step(db, run_id)
    db_v_dc = _count_db_distinct_companies_validated_with_email(db, run_id)
    contacts_validated_distinct_companies = max(step_v_dc or 0, db_v_dc)
    contacts_with_no_email = _count_db_contacts_no_email(db, run_id)
    return {
        "companies_collected": n_co,
        "contacts_found": contacts_found,
        "contacts_validated": contacts_validated,
        "contacts_validated_distinct_companies": contacts_validated_distinct_companies,
        "contacts_with_no_email": contacts_with_no_email,
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


def setup_state_message_from_phase(phase: str) -> str:
    if phase == "Ready":
        return "This run is ready for outreach"
    if phase in ("Active", "Closed"):
        return "Run setup is complete"
    return "Run setup is in progress"


def get_run_display_phase_lite(db: Session, run) -> str:
    """Same labels as get_run_display_phase; uses COUNT queries only (no full run summary)."""
    if run.closed_at is not None:
        return "Closed"
    if run.status == "drafts_ready":
        return "Ready"
    rid = run.id
    n_draft_sent = (
        db.query(func.count())
        .select_from(EmailDraft)
        .filter(EmailDraft.run_id == rid, EmailDraft.status == "sent")
        .scalar()
        or 0
    )
    if int(n_draft_sent) > 0:
        return "Active"
    n_ev_sent = (
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == rid, EmailEvent.event_type == "sent")
        .scalar()
        or 0
    )
    if int(n_ev_sent) > 0:
        return "Active"
    return "Preparing"


def get_run_performance_lite(db: Session, run_id: int) -> dict:
    """Same keys as get_run_performance_rows; COUNT-based (no get_run_summary)."""
    drafts_sent = int(
        db.query(func.count())
        .select_from(EmailDraft)
        .filter(EmailDraft.run_id == run_id, EmailDraft.status == "sent")
        .scalar()
        or 0
    )
    events_replied = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == run_id, EmailEvent.event_type == "replied")
        .scalar()
        or 0
    )
    threads_interested = int(
        db.query(func.count())
        .select_from(EmailThread)
        .filter(EmailThread.run_id == run_id, EmailThread.classification == "interested")
        .scalar()
        or 0
    )
    threads_need_info = int(
        db.query(func.count())
        .select_from(EmailThread)
        .filter(EmailThread.run_id == run_id, EmailThread.classification == "need_more_info")
        .scalar()
        or 0
    )
    ev_bounced = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == run_id, EmailEvent.event_type == "bounced")
        .scalar()
        or 0
    )
    ev_dead = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == run_id, EmailEvent.event_type == "dead_mailbox")
        .scalar()
        or 0
    )
    active_threads = _active_threads_count_for_performance(db, run_id)
    return {
        "emails_sent": drafts_sent,
        "emails_sent_24h": count_emails_sent_in_last_hours(db, run_id, hours=24),
        "replies": events_replied,
        "active_threads": active_threads,
        "interested": threads_interested,
        "need_more_info": threads_need_info,
        "dead_mailboxes": ev_dead,
        "bounced": ev_bounced,
    }


def get_conversations_lite(db: Session, run_id: int) -> dict:
    """Same keys as get_conversations_snapshot; avoids get_run_summary."""
    active_threads = _active_threads_count_for_performance(db, run_id)
    replies_received = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == run_id, EmailEvent.event_type == "replied")
        .scalar()
        or 0
    )
    reply_drafts = int(
        db.query(func.count()).select_from(ReplyDraft).filter(ReplyDraft.run_id == run_id).scalar() or 0
    )
    reminders = list_reminders_by_run(db, run_id)
    now = datetime.utcnow()
    reminders_due, reminders_active = _reminder_due_and_active_counts(reminders, now)
    return {
        "active_threads": active_threads,
        "replies_received": replies_received,
        "reply_drafts": reply_drafts,
        "reminders_active": reminders_active,
        "reminders_due": reminders_due,
    }


def build_run_workspace_lite(db: Session, run) -> dict:
    phase = get_run_display_phase_lite(db, run)
    rid = run.id
    return {
        "display_phase": phase,
        "setup_state_message": setup_state_message_from_phase(phase),
        "performance": get_run_performance_lite(db, rid),
        "conversations": get_conversations_lite(db, rid),
        "hourly_sends_24h": hourly_send_counts_24h_utc(db, rid),
    }


def get_conversations_snapshot(db: Session, run_id: int) -> dict:
    summary = get_run_summary(db, run_id)
    active_threads = _active_threads_count_for_performance(db, run_id)
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


def get_total_performance_global(db: Session) -> dict:
    """All projects/runs: outreach + reply sends. Outreach uses max(drafts marked sent, distinct sent events)."""
    n_out_draft = (
        db.query(func.count()).select_from(EmailDraft).filter(EmailDraft.status == "sent").scalar()
    )
    n_out_draft = int(n_out_draft or 0)
    n_out_ev = (
        db.query(func.count(func.distinct(EmailEvent.draft_id)))
        .select_from(EmailEvent)
        .filter(EmailEvent.event_type == "sent")
        .scalar()
    )
    n_out_ev = int(n_out_ev or 0)
    n_outreach_all = max(n_out_draft, n_out_ev)

    n_reply_all = db.query(func.count()).select_from(ReplyDraft).filter(ReplyDraft.status == "sent").scalar()
    n_reply_all = int(n_reply_all or 0)
    emails_sent = n_outreach_all + n_reply_all

    cutoff = datetime.utcnow() - timedelta(hours=24)
    n_out_24_draft = (
        db.query(func.count())
        .select_from(EmailDraft)
        .filter(
            EmailDraft.status == "sent",
            EmailDraft.sent_at.isnot(None),
            EmailDraft.sent_at >= cutoff,
        )
        .scalar()
    )
    n_out_24_draft = int(n_out_24_draft or 0)
    n_out_24_ev = (
        db.query(func.count(func.distinct(EmailEvent.draft_id)))
        .select_from(EmailEvent)
        .filter(EmailEvent.event_type == "sent", EmailEvent.created_at >= cutoff)
        .scalar()
    )
    n_out_24_ev = int(n_out_24_ev or 0)
    n_outreach_24h = max(n_out_24_draft, n_out_24_ev)

    n_reply_24 = (
        db.query(func.count())
        .select_from(ReplyDraft)
        .filter(
            ReplyDraft.status == "sent",
            ReplyDraft.sent_at.isnot(None),
            ReplyDraft.sent_at >= cutoff,
        )
        .scalar()
    )
    n_reply_24 = int(n_reply_24 or 0)
    emails_sent_24h = n_outreach_24h + n_reply_24
    return {"emails_sent": emails_sent, "emails_sent_24h": emails_sent_24h}


def get_run_performance_rows(db: Session, run_id: int) -> dict:
    """Counters for Run performance card; omit keys with no data yet where appropriate."""
    summary = get_run_summary(db, run_id)
    active_threads = _active_threads_count_for_performance(db, run_id)

    return {
        "emails_sent": summary["drafts_sent"],
        "emails_sent_24h": count_emails_sent_in_last_hours(db, run_id, hours=24),
        "replies": summary["events_replied"],
        "active_threads": active_threads,
        "interested": summary["threads_interested"],
        "need_more_info": summary["threads_need_info"],
        "dead_mailboxes": summary["events_dead_mailbox"],
        "bounced": summary["events_bounced"],
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
    active_threads = _active_threads_count_for_performance(db, run.id)
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
        "prompt_setup_saved": prompt_setup_saved_from_context(run.context_json),
        "sender_signature_configured": signature_html_has_meaningful_content(run.sender_signature_html),
    }


