"""Contact analyzer: one-time Gmail search per address (to/from), stored on contacts."""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories.contact_repo import apply_gmail_history_to_contacts, list_contacts_raw_by_run
from app.repositories.run_repo import get_run
from app.services.gmail_oauth import (
    GmailOAuthError,
    gmail_has_to_or_from_correspondence,
    google_client_configured,
    google_refresh_token_value,
    refresh_access_token,
)

GMAIL_HISTORY_NO = "no_history"
GMAIL_HISTORY_YES = "history_detected"


def _badge_sort_rank(agg_status: str | None) -> int:
    """Contact analyzer table order: Not verified → No history → History detected."""
    if agg_status is None:
        return 0
    if agg_status == GMAIL_HISTORY_NO:
        return 1
    if agg_status == GMAIL_HISTORY_YES:
        return 2
    return 3


def _norm_email_key(e: str | None) -> str | None:
    s = (e or "").strip().lower()
    return s if s and "@" in s else None


def group_contacts_by_email(contacts: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in contacts:
        key = _norm_email_key(c.email)
        if not key:
            continue
        out.setdefault(key, []).append(c)
    return out


def list_contact_analyzer_rows(db: Session, run_id: int) -> list[dict]:
    if not get_run(db, run_id):
        return []
    raw = list_contacts_raw_by_run(db, run_id)
    groups = group_contacts_by_email(raw)
    rows: list[dict] = []
    for email_key in sorted(groups.keys()):
        group = groups[email_key]
        display_email = (group[0].email or "").strip()
        statuses = [g.gmail_history_status for g in group]
        times = [g.gmail_history_checked_at for g in group]
        import_times = [g.gmail_inbox_imported_at for g in group]
        if any(s is None for s in statuses):
            agg_status = None
            agg_checked = None
        else:
            agg_status = statuses[0]
            agg_checked = max(t for t in times if t is not None) if times else None
        if any(t is None for t in import_times):
            agg_imported = None
        else:
            agg_imported = max(t for t in import_times if t is not None) if import_times else None
        rows.append(
            {
                "email": display_email or email_key,
                "email_normalized": email_key,
                "contact_ids": [c.id for c in group],
                "gmail_history_status": agg_status,
                "gmail_history_checked_at": agg_checked,
                "gmail_inbox_imported_at": agg_imported,
            },
        )
    rows.sort(key=lambda r: (_badge_sort_rank(r["gmail_history_status"]), r["email_normalized"]))
    return rows


def mark_history_detected_after_outbound_send(
    db: Session,
    run_id: int,
    to_email: str | None,
) -> None:
    """After a successful system send to to_email, set Contact analyzer to history_detected for that address in run."""
    key = _norm_email_key(to_email)
    if not key:
        return
    if not get_run(db, run_id):
        return
    raw = list_contacts_raw_by_run(db, run_id)
    groups = group_contacts_by_email(raw)
    group = groups.get(key)
    if not group:
        return
    apply_gmail_history_to_contacts(
        db,
        group,
        status=GMAIL_HISTORY_YES,
        checked_at=datetime.utcnow(),
    )


def require_gmail_configured() -> None:
    if not google_client_configured() or not google_refresh_token_value():
        raise ValueError("Gmail is not connected — complete OAuth in Drafts / setup first.")


def verify_run_email(
    db: Session,
    run_id: int,
    email_normalized: str,
    *,
    access_token: str | None = None,
) -> dict:
    require_gmail_configured()
    if not get_run(db, run_id):
        raise ValueError("Run not found")

    key = _norm_email_key(email_normalized)
    if not key:
        raise ValueError("Invalid email")

    raw = list_contacts_raw_by_run(db, run_id)
    groups = group_contacts_by_email(raw)
    group = groups.get(key)
    if not group:
        raise ValueError("No contact with this email in this run")

    if any(c.gmail_history_status is not None for c in group):
        raise ValueError("This address was already verified — Gmail is not queried again.")

    token = access_token or refresh_access_token()
    try:
        has_history = gmail_has_to_or_from_correspondence(token, key)
    except GmailOAuthError:
        raise
    status = GMAIL_HISTORY_YES if has_history else GMAIL_HISTORY_NO
    checked = datetime.utcnow()
    apply_gmail_history_to_contacts(db, group, status=status, checked_at=checked)
    return {"email_normalized": key, "gmail_history_status": status}


def verify_all_unverified_emails(db: Session, run_id: int) -> dict:
    require_gmail_configured()
    if not get_run(db, run_id):
        raise ValueError("Run not found")

    rows = list_contact_analyzer_rows(db, run_id)
    token = refresh_access_token()
    verified = 0
    failures: list[dict] = []

    for row in rows:
        if row["gmail_history_status"] is not None:
            continue
        em = row["email_normalized"]
        try:
            verify_run_email(db, run_id, em, access_token=token)
            verified += 1
        except GmailOAuthError as e:
            failures.append({"email": em, "error": str(e)})
            break
        except ValueError as e:
            failures.append({"email": em, "error": str(e)})
        time.sleep(0.2)

    return {"verified": verified, "failures": failures}
