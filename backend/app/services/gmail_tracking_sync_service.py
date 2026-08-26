"""Gmail: incremental thread sync (replies), bounce / DSN handling, RFC Message-ID correlation."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.run import Run
from app.repositories.email_draft_repo import get_email_draft
from app.repositories.email_message_repo import (
    create_email_message,
    get_email_message_by_provider_id,
    get_email_message_by_rfc_message_id,
)
from app.repositories.email_thread_repo import bump_email_thread_last_message_at, list_email_threads_by_run
from app.repositories.gmail_processed_repo import (
    gmail_notification_already_processed,
    record_gmail_notification_processed,
)
from app.repositories.run_repo import get_run
from app.services.contact_gmail_history_service import require_gmail_configured
from app.services.email_tracking_service import (
    register_bounced_event,
    register_dead_mailbox_event,
    register_replied_event,
)
from app.services.inbound_delivery_llm_service import (
    inbound_message_should_run_llm_delivery_check,
    maybe_apply_inbound_delivery_llm_after_message,
)
from app.services.inbox_service import apply_reply_classification
from app.services.gmail_inbox_import_service import (
    _header_map,
    _norm,
    _our_address_set,
    _parse_gmail_full,
)
from app.services.gmail_oauth import (
    GmailOAuthError,
    gmail_get_message_full,
    gmail_get_thread_full,
    gmail_list_message_refs_paginated,
    normalize_rfc_message_id_header,
    refresh_access_token,
)

_log = logging.getLogger(__name__)

_SMTP_STATUS_RE = re.compile(r"\b([45]\d\d\b[\s\-–:][^\n]{1,200})", re.IGNORECASE)


def _short_bounce_summary_for_event(combined_text: str) -> str | None:
    """One-line SMTP-style status for email_events; avoids multi-KB DSN/HTML in the DB/UI."""
    if not (combined_text or "").strip():
        return None
    m = _SMTP_STATUS_RE.search(combined_text.replace("\r", ""))
    if m:
        return m.group(1).strip()[:220]
    stripped = re.sub(r"\s+", " ", combined_text).strip()
    return (stripped[:180] + "…") if len(stripped) > 180 else stripped or None


BOUNCE_GMAIL_QUERY = (
    "newer_than:14d "
    "(from:mailer-daemon OR from:mailerdaemon OR from:postmaster "
    'OR subject:"Delivery Status" OR subject:Undeliverable OR subject:"failure notice")'
)

_DEAD_MAILBOX_HINTS = re.compile(
    "|".join(
        [
            r"5\.1\.1",
            r"\b550\b",
            r"\b551\b",
            r"\b553\b",
            r"user unknown",
            r"unknown user",
            r"address rejected",
            r"no mailbox",
            r"does not exist",
            r"recipient address rejected",
            r"invalid.*recipient",
            r"mailbox unavailable",
        ],
    ),
    re.I,
)


def _reference_ids_from_headers(hmap: dict[str, str]) -> list[str]:
    out: list[str] = []
    for key in ("in-reply-to", "references"):
        raw = hmap.get(key)
        if not raw:
            continue
        for m in re.finditer(r"<([^>]+)>", raw):
            nid = normalize_rfc_message_id_header(f"<{m.group(1)}>")
            if nid:
                out.append(nid)
    return out


def _should_mark_replied(
    db: Session,
    draft_id: int,
    inbound_dt: datetime,
    from_email: str,
) -> bool:
    draft = get_email_draft(db, draft_id)
    if not draft:
        return False
    if draft.status != "sent" or draft.tracking_status != "sent":
        return False
    if not draft.sent_at or inbound_dt <= draft.sent_at:
        return False
    to_n = _norm(draft.to_email)
    from_n = _norm(from_email)
    if to_n and from_n and to_n == from_n:
        return True
    return False


def sync_thread_messages_for_run(
    db: Session,
    run_id: int,
    *,
    access_token: str | None = None,
) -> dict:
    """Pull new messages for all run threads that have a Gmail thread id."""
    require_gmail_configured()
    if not get_run(db, run_id):
        return {"run_id": run_id, "error": "run not found", "imported": 0, "replied_marked": 0}

    token = access_token or refresh_access_token()
    our = _our_address_set(token)
    threads = list_email_threads_by_run(db, run_id)
    imported = 0
    replied_marked = 0
    thread_errors: list[str] = []

    for th in threads:
        g_tid = (th.provider_thread_id or "").strip()
        if not g_tid:
            continue
        try:
            raw_thread = gmail_get_thread_full(token, g_tid)
        except GmailOAuthError as e:
            thread_errors.append(f"thread_db={th.id} gmail={g_tid}: {e}")
            continue

        msgs = raw_thread.get("messages") or []
        msgs_sorted = [m for m in msgs if isinstance(m, dict)]
        msgs_sorted.sort(key=lambda m: int(m.get("internalDate") or 0))

        for m in msgs_sorted:
            mid = str(m.get("id") or "").strip()
            if not mid or get_email_message_by_provider_id(db, mid):
                continue
            parsed = _parse_gmail_full(m)
            if not parsed:
                continue

            is_out = bool(parsed.from_addresses & our)
            direction = "outbound" if is_out else "inbound"
            draft_id_for_row = th.draft_id if direction == "outbound" else None

            create_email_message(
                db=db,
                thread_id=th.id,
                run_id=run_id,
                contact_id=th.contact_id,
                draft_id=draft_id_for_row,
                direction=direction,
                from_email=parsed.from_email or None,
                to_email=parsed.to_email or None,
                subject=parsed.subject,
                body=parsed.body,
                provider_message_id=parsed.provider_message_id,
                rfc_message_id=parsed.rfc_message_id,
            )
            imported += 1
            bump_email_thread_last_message_at(db, th, parsed.internal_dt)

            if direction == "inbound" and th.draft_id:
                try:
                    maybe_apply_inbound_delivery_llm_after_message(
                        db,
                        draft_id=th.draft_id,
                        from_email=parsed.from_email,
                        subject=parsed.subject or "",
                        body=parsed.body or "",
                        gmail_message_id=mid,
                    )
                except Exception:
                    _log.debug("inbound LLM delivery pass failed thread=%s", th.id, exc_info=True)

                # B-138: classify the reply and drive follow-up/suppression from the real sync path
                # (previously only a dev/mock endpoint did this — thread.classification was never
                # set for real replies). Skip DSN/bounce/mailer-daemon-looking messages — same
                # heuristic gate used above for the delivery-check LLM pass, so a bounce notice
                # never gets classified as e.g. "not_interested". Re-classifying an already-
                # classified thread on a later inbound message is intentional (dialogue moves on).
                # apply_reply_classification -> classify_reply strips quoted history first, so our
                # own "reply STOP" opt-out text echoed back in the quote doesn't false-positive.
                if not inbound_message_should_run_llm_delivery_check(
                    from_email=parsed.from_email,
                    subject=parsed.subject or "",
                    body=parsed.body or "",
                ):
                    try:
                        apply_reply_classification(db, th, parsed.body, create_task=True)
                    except Exception:
                        _log.debug("reply classification failed thread=%s", th.id, exc_info=True)

            if direction == "inbound" and th.draft_id and _should_mark_replied(
                db,
                th.draft_id,
                parsed.internal_dt,
                parsed.from_email,
            ):
                try:
                    out = register_replied_event(
                        db,
                        th.draft_id,
                        payload_json={"source": "gmail_thread_sync", "gmail_message_id": mid},
                        classification=th.classification,
                    )
                    if not out.get("skipped"):
                        replied_marked += 1
                except ValueError:
                    _log.debug("register_replied_event skipped draft_id=%s", th.draft_id)

        time.sleep(0.06)

    return {
        "run_id": run_id,
        "imported": imported,
        "replied_marked": replied_marked,
        "threads_seen": len([t for t in threads if (t.provider_thread_id or "").strip()]),
        "errors": thread_errors or None,
    }


def sync_bounce_notifications(
    db: Session,
    *,
    access_token: str | None = None,
    max_messages: int = 50,
) -> dict:
    """Match DSN / bounce emails to outbound Message-ID and update draft tracking."""
    require_gmail_configured()
    token = access_token or refresh_access_token()
    applied_bounce = 0
    applied_dead = 0
    skipped = 0

    try:
        refs = gmail_list_message_refs_paginated(token, BOUNCE_GMAIL_QUERY)
    except GmailOAuthError as e:
        return {"error": str(e), "applied_bounce": 0, "applied_dead_mailbox": 0}

    for ref in refs[:max_messages]:
        mid = str(ref.get("id") or "").strip()
        if not mid:
            continue
        if gmail_notification_already_processed(db, mid, "bounce"):
            skipped += 1
            continue
        try:
            raw = gmail_get_message_full(token, mid)
        except GmailOAuthError:
            record_gmail_notification_processed(db, mid, "bounce")
            continue

        parsed = _parse_gmail_full(raw)
        if not parsed:
            record_gmail_notification_processed(db, mid, "bounce")
            continue

        payload = raw.get("payload")
        headers_list = payload.get("headers") if isinstance(payload, dict) else None
        hmap = _header_map(headers_list if isinstance(headers_list, list) else [])
        ref_ids = _reference_ids_from_headers(hmap)

        orig = None
        for rid in ref_ids:
            orig = get_email_message_by_rfc_message_id(db, rid)
            if orig and orig.draft_id:
                break

        combined = f"{parsed.body or ''} {raw.get('snippet') or ''}"
        excerpt = ((parsed.subject or "") + " — " + (parsed.body or ""))[:1200]
        event_err = _short_bounce_summary_for_event(combined) or "Delivery failed"
        bounce_payload = {
            "gmail_message_id": mid,
            "source": "gmail_bounce_sync",
            "notification_excerpt": excerpt[:800],
        }

        if orig and orig.draft_id:
            draft = get_email_draft(db, orig.draft_id)
            if draft and draft.status == "sent":
                try:
                    if _DEAD_MAILBOX_HINTS.search(combined):
                        out = register_dead_mailbox_event(
                            db,
                            draft.id,
                            payload_json=bounce_payload,
                            error_message=event_err,
                        )
                        if not out.get("skipped"):
                            applied_dead += 1
                    else:
                        out = register_bounced_event(
                            db,
                            draft.id,
                            payload_json=bounce_payload,
                            error_message=event_err,
                        )
                        if not out.get("skipped"):
                            applied_bounce += 1
                except ValueError:
                    _log.exception("bounce sync apply failed draft_id=%s", orig.draft_id)

        record_gmail_notification_processed(db, mid, "bounce")
        time.sleep(0.05)

    return {
        "applied_bounce": applied_bounce,
        "applied_dead_mailbox": applied_dead,
        "skipped_already_processed": skipped,
        "listed": min(len(refs), max_messages),
    }


def sync_gmail_for_run(db: Session, run_id: int, *, access_token: str | None = None) -> dict:
    """Threads (replies) for one run + global bounce pass."""
    a = sync_thread_messages_for_run(db, run_id, access_token=access_token)
    b = sync_bounce_notifications(db, access_token=access_token)
    return {"threads": a, "bounces": b}


def sync_gmail_all_open_runs(db: Session, *, access_token: str | None = None) -> dict:
    run_ids = [
        row[0]
        for row in db.query(Run.id).filter(Run.closed_at.is_(None)).order_by(Run.id.asc()).all()
    ]
    combined: list[dict] = []
    bounce_once = sync_bounce_notifications(db, access_token=access_token)
    for rid in run_ids:
        combined.append(sync_thread_messages_for_run(db, rid, access_token=access_token))
    return {"runs": len(run_ids), "per_run": combined, "bounces": bounce_once}
