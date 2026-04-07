"""Computed run phase and dashboard fields for human UI (run-centered)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_event import EmailEvent
from app.models.reply_draft import ReplyDraft
from app.models.email_thread import EmailThread
from app.repositories.reminder_repo import list_reminders_by_run
from app.repositories.step_repo import get_step_by_run_and_name
from app.repositories.run_repo import get_run
from app.services.run_context_service import get_prompt_setup_text, get_sender_signature_html
from app.setup_milestones import (
    SETUP_MILESTONE_COMPANIES,
    SETUP_MILESTONE_CONTACTS,
    SETUP_MILESTONE_VALID_CONTACTS,
)

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


_DEFAULT_OUTREACH_BRIEF = (
    "Respondent's field of activity:\n\n"
    "Narrowly focused areas of activity:\n\n"
    "Reason for search (licensing, sales, partnership):\n\n"
    "How long has the respondent company been in the market:\n\n"
    "Additional information:\n\n"
)


def _context_from_run_for_prompt_ui(run) -> dict | None:
    """Mirror AiBizOsHumanUI `contextFromRun` for Prompt setup editor default."""
    from app.services.run_context_service import get_effective_context

    ctx = get_effective_context(run)
    if not any(str(v or "").strip() for v in ctx.values()):
        return None
    return ctx


def _context_to_outreach_brief_text(ctx: dict | None) -> str:
    """Mirror AiBizOsHumanUI `contextToOutreachBriefText` (search brief form)."""
    from app.services.run_context_service import format_search_brief_from_inner

    if not ctx:
        return _DEFAULT_OUTREACH_BRIEF
    return format_search_brief_from_inner(ctx)


def get_prompt_setup_editor_initial_text_for_ui(run) -> str:
    """Same string the Human UI Prompt setup dialog would show (saved textarea or derived brief)."""
    saved = get_prompt_setup_text(run)
    if saved.strip():
        return saved
    ctx = _context_from_run_for_prompt_ui(run)
    if ctx is None:
        return _DEFAULT_OUTREACH_BRIEF
    return _context_to_outreach_brief_text(ctx)


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

    stmt = union_all(
        select(EmailDraft.sent_at).where(
            EmailDraft.run_id == run_id,
            EmailDraft.status == "sent",
            EmailDraft.sent_at.isnot(None),
            EmailDraft.sent_at >= start,
            EmailDraft.sent_at <= now,
        ),
        select(ReplyDraft.sent_at).where(
            ReplyDraft.run_id == run_id,
            ReplyDraft.status == "sent",
            ReplyDraft.sent_at.isnot(None),
            ReplyDraft.sent_at >= start,
            ReplyDraft.sent_at <= now,
        ),
    )
    for (st,) in db.execute(stmt):
        bump(st)

    return buckets


def _live_validated_email_and_distinct_company_counts_sql(db: Session, run_id: int) -> tuple[int, int]:
    """COUNT-only: valid/invalid rows with email + distinct company keys (no full ORM list)."""
    email_count = int(
        db.query(func.count())
        .select_from(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.status.in_(("valid", "invalid")),
            Contact.email.isnot(None),
            Contact.email != "",
        )
        .scalar()
        or 0
    )
    distinct_expr = func.concat(
        func.lower(func.trim(func.coalesce(Contact.company, ""))),
        "\x1f",
        func.lower(func.trim(func.coalesce(Contact.website, ""))),
    )
    distinct_count = int(
        db.query(func.count(func.distinct(distinct_expr)))
        .select_from(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.status.in_(("valid", "invalid")),
            Contact.email.isnot(None),
            Contact.email != "",
            or_(
                func.trim(func.coalesce(Contact.company, "")) != "",
                func.trim(func.coalesce(Contact.website, "")) != "",
            ),
        )
        .scalar()
        or 0
    )
    return email_count, distinct_count


def _approved_reachable_and_no_email_counts_sql(db: Session, run_id: int) -> tuple[int, int]:
    """Approved+reachable count and contacts with empty email (raw rows; no dedupe)."""
    approved = int(
        db.query(func.count())
        .select_from(Contact)
        .filter(
            Contact.run_id == run_id,
            Contact.review_status.in_(["approved", "edited"]),
            or_(
                Contact.email_health.is_(None),
                Contact.email_health.notin_(["bounced", "dead_mailbox"]),
            ),
        )
        .scalar()
        or 0
    )
    no_email = int(
        db.query(func.count())
        .select_from(Contact)
        .filter(
            Contact.run_id == run_id,
            or_(Contact.email.is_(None), Contact.email == ""),
        )
        .scalar()
        or 0
    )
    return approved, no_email


def _live_company_count(db: Session, run_id: int) -> int:
    """Count collected company rows (run_companies)."""
    from app.repositories.run_company_repo import count_run_companies

    return count_run_companies(db, run_id)


def _live_contact_count(db: Session, run_id: int) -> int:
    """Contacts for the run — from ``contacts`` table (not find_contacts step JSON)."""
    n = (
        db.query(func.count())
        .select_from(Contact)
        .filter(Contact.run_id == run_id)
        .scalar()
    )
    return int(n or 0)


def _live_valid_contact_count(db: Session, run_id: int) -> int:
    n = (
        db.query(func.count())
        .select_from(Contact)
        .filter(Contact.run_id == run_id, Contact.status == "valid")
        .scalar()
    )
    return int(n or 0)


def _active_threads_count_for_performance(db: Session, run_id: int) -> int:
    """Threads excluding bounced/dead — SQL-fast for metrics (no full thread/draft/message scan).

    Approximates TrackingView \"active\": contact ``email_health`` + linked ``draft_id`` draft rows.
    Threads whose outbound draft is only inferred (null ``draft_id``) may differ from the full UI resolver.
    """
    total = int(
        db.query(func.count()).select_from(EmailThread).filter(EmailThread.run_id == run_id).scalar() or 0
    )
    if total == 0:
        return 0

    bad_from_contact = (
        db.query(EmailThread.id)
        .join(Contact, Contact.id == EmailThread.contact_id)
        .filter(EmailThread.run_id == run_id)
        .filter(Contact.email_health.in_(["bounced", "dead_mailbox"]))
    )
    ts_tr = func.trim(EmailDraft.tracking_status)
    lifecycle = case(
        (func.length(ts_tr) > 0, func.lower(ts_tr)),
        else_=func.lower(func.trim(EmailDraft.status)),
    )
    bad_from_draft = (
        db.query(EmailThread.id)
        .join(EmailDraft, EmailDraft.id == EmailThread.draft_id)
        .filter(EmailThread.run_id == run_id)
        .filter(
            or_(
                func.lower(ts_tr) == "bounced",
                lifecycle == "dead_mailbox",
            )
        )
    )
    bad_subq = bad_from_contact.union(bad_from_draft).subquery()
    n_bad = int(db.query(func.count()).select_from(bad_subq).scalar() or 0)
    return max(0, total - n_bad)


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
    """Setup contact/company counts from ``contacts`` / ``run_companies`` tables."""
    n_co = _live_company_count(db, run_id)
    n_fi = _live_contact_count(db, run_id)
    contacts_found = n_fi
    contacts_validated, contacts_validated_distinct_companies = _live_validated_email_and_distinct_company_counts_sql(
        db,
        run_id,
    )
    contacts_approved, contacts_with_no_email = _approved_reachable_and_no_email_counts_sql(db, run_id)
    return {
        "companies_collected": n_co,
        "contacts_found": contacts_found,
        "contacts_validated": contacts_validated,
        "contacts_validated_distinct_companies": contacts_validated_distinct_companies,
        "contacts_with_no_email": contacts_with_no_email,
        "contacts_approved": contacts_approved,
    }


def get_run_display_phase(db: Session, run) -> str:
    """Preparing | Ready | Active | Closed (exact UI labels)."""
    return get_run_display_phase_lite(db, run)


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


def get_run_performance_lite(
    db: Session,
    run_id: int,
    *,
    active_threads: int | None = None,
    replies_received: int | None = None,
) -> dict:
    """Same keys as get_run_performance_rows; COUNT-based (no get_run_summary)."""
    drafts_sent = int(
        db.query(func.count())
        .select_from(EmailDraft)
        .filter(EmailDraft.run_id == run_id, EmailDraft.status == "sent")
        .scalar()
        or 0
    )
    if replies_received is None:
        replies_received = int(
            db.query(func.count())
            .select_from(EmailEvent)
            .filter(EmailEvent.run_id == run_id, EmailEvent.event_type == "replied")
            .scalar()
            or 0
        )
    events_replied = replies_received
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
    if active_threads is None:
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


def get_conversations_lite(
    db: Session,
    run_id: int,
    *,
    active_threads: int | None = None,
    replies_received: int | None = None,
) -> dict:
    """Same keys as get_conversations_snapshot; avoids get_run_summary."""
    if active_threads is None:
        active_threads = _active_threads_count_for_performance(db, run_id)
    if replies_received is None:
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
    active_threads = _active_threads_count_for_performance(db, rid)
    replies_received = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == rid, EmailEvent.event_type == "replied")
        .scalar()
        or 0
    )
    return {
        "display_phase": phase,
        "setup_state_message": setup_state_message_from_phase(phase),
        "setup_summary": get_run_setup_summary(db, rid),
        "performance": get_run_performance_lite(
            db, rid, active_threads=active_threads, replies_received=replies_received
        ),
        "conversations": get_conversations_lite(
            db, rid, active_threads=active_threads, replies_received=replies_received
        ),
        "hourly_sends_24h": hourly_send_counts_24h_utc(db, rid),
    }


def build_run_workspace_tick(db: Session, run) -> dict:
    """Minimal poll payload: phase + setup_summary + performance counts only.

    Skips hourly bucket scan, reminder list load, and conversation reminder rollups — use
    :func:`build_run_workspace_lite` for full dashboard (chart + sidebar conversation counts).
    """
    phase = get_run_display_phase_lite(db, run)
    rid = run.id
    active_threads = _active_threads_count_for_performance(db, rid)
    replies_received = int(
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.run_id == rid, EmailEvent.event_type == "replied")
        .scalar()
        or 0
    )
    return {
        "display_phase": phase,
        "setup_state_message": setup_state_message_from_phase(phase),
        "setup_summary": get_run_setup_summary(db, rid),
        "performance": get_run_performance_lite(
            db, rid, active_threads=active_threads, replies_received=replies_received
        ),
    }


def get_conversations_snapshot(db: Session, run_id: int) -> dict:
    return get_conversations_lite(db, run_id)


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

    n_replies = (
        db.query(func.count())
        .select_from(EmailEvent)
        .filter(EmailEvent.event_type == "replied")
        .scalar()
    )
    n_replies = int(n_replies or 0)
    return {"emails_sent": emails_sent, "emails_sent_24h": emails_sent_24h, "replies": n_replies}


def get_run_performance_rows(db: Session, run_id: int) -> dict:
    """Counters for Run performance card; COUNT-based (no full run summary)."""
    p = get_run_performance_lite(db, run_id)
    return {
        "emails_sent": p["emails_sent"],
        "emails_sent_24h": p["emails_sent_24h"],
        "replies": p["replies"],
        "active_threads": p["active_threads"],
        "interested": p["interested"],
        "need_more_info": p["need_more_info"],
        "dead_mailboxes": p["dead_mailboxes"],
        "bounced": p["bounced"],
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
    rid = run.id
    perf = get_run_performance_lite(db, rid)
    companies = _live_company_count(db, rid)
    contacts_found = _live_contact_count(db, rid)

    name = run.name or f"Run #{run.id}"
    return {
        "id": run.id,
        "project_id": run.project_id,
        "name": name,
        "notes": run.notes,
        "segment": run.segment,
        "status": run.status,
        "display_phase": get_run_display_phase_lite(db, run),
        "closed_at": run.closed_at,
        "companies_count": companies,
        "contacts_count": contacts_found,
        "emails_sent": perf["emails_sent"],
        "replies": perf["replies"],
        "active_threads": perf["active_threads"],
        "created_at": run.created_at,
        "prompt_setup_saved": bool(get_prompt_setup_text(run).strip()),
        "sender_signature_configured": signature_html_has_meaningful_content(get_sender_signature_html(run)),
    }


