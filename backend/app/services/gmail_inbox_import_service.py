"""Import Gmail inbox + sent (last 6 months) for a contact-analyzer address into email_threads / email_messages."""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from datetime import datetime
from email.utils import getaddresses

from sqlalchemy.orm import Session

from app.repositories.contact_repo import apply_gmail_inbox_imported_at, list_contacts_raw_by_run
from app.repositories.email_message_repo import create_email_message, get_email_message_by_provider_id
from app.repositories.email_thread_repo import (
    bump_email_thread_last_message_at,
    create_email_thread,
    find_email_thread_by_run_contact_gmail,
)
from app.repositories.run_repo import get_run
from app.services.contact_gmail_history_service import (
    GMAIL_HISTORY_YES,
    group_contacts_by_email,
    require_gmail_configured,
)
from app.services.gmail_oauth import (
    GmailOAuthError,
    gmail_get_message_full,
    gmail_list_message_refs_paginated,
    gmail_profile_email,
    list_send_as_emails,
    normalize_rfc_message_id_header,
    refresh_access_token,
)
from app.services.outbound_email_body import html_to_plain_text_for_mime, looks_like_html_fragment


def _norm(s: str | None) -> str:
    x = (s or "").strip().lower()
    return x if x and "@" in x else ""


def _decode_b64url(data: str | None) -> str:
    if not data:
        return ""
    pad = 4 - len(data) % 4
    if pad != 4:
        data += "=" * pad
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _header_map(headers: list) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers or []:
        if not isinstance(h, dict):
            continue
        name = str(h.get("name") or "").strip()
        if not name:
            continue
        out[name.lower()] = str(h.get("value") or "")
    return out


def _addresses_from_header(hdr: str | None) -> list[str]:
    if not hdr:
        return []
    out: list[str] = []
    for _, addr in getaddresses([hdr]):
        a = _norm(addr)
        if a:
            out.append(a)
    return out


def _first_address(hdr: str | None) -> str:
    xs = _addresses_from_header(hdr)
    return xs[0] if xs else ""


_GMAIL_SIGNATURE_DIV = re.compile(r'(?is)<div[^>]*\bgmail_signature\b[^>]*>.*')
_GMAIL_QUOTE_DIV = re.compile(r'(?is)<div[^>]*\bgmail_quote\b[^>]*>.*')


def _decode_part_body(part: dict) -> str:
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    return _decode_b64url(str(body.get("data") or ""))


def _body_from_mime_part(part: dict) -> str:
    """Pick one body: in multipart/alternative use the last HTML (or plain) only — do not merge siblings."""
    if not isinstance(part, dict):
        return ""
    mime = str(part.get("mimeType") or "").lower()
    if mime.startswith("multipart/"):
        subs = [p for p in part.get("parts") or [] if isinstance(p, dict)]
        if mime == "multipart/alternative":
            html_parts = [p for p in subs if str(p.get("mimeType") or "").lower() == "text/html"]
            plain_parts = [p for p in subs if str(p.get("mimeType") or "").lower() == "text/plain"]
            if html_parts:
                return _decode_part_body(html_parts[-1])
            if plain_parts:
                return _decode_part_body(plain_parts[-1])
            return ""
        for sub in subs:
            got = _body_from_mime_part(sub)
            if got.strip():
                return got
        return ""
    if mime == "text/html":
        return _decode_part_body(part)
    if mime == "text/plain":
        return _decode_part_body(part)
    return ""


def _raw_body_from_payload(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return _body_from_mime_part(payload).strip()


def _strip_common_email_html_boilerplate(html: str) -> str:
    t = html or ""
    t = _GMAIL_SIGNATURE_DIV.sub("", t)
    t = _GMAIL_QUOTE_DIV.sub("", t)
    return t


def _trim_signature_plain(text: str) -> str:
    """Cut at a lone '--' line (common signature / disclaimer separator)."""
    lines = (text or "").splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "--" and i > 0:
            break
        out.append(line)
    return "\n".join(out).strip()


def _normalize_imported_message_body(raw: str) -> str:
    """Readable plain text for thread UI — no glued MIME fragments or nested signature HTML."""
    s = (raw or "").strip()
    if not s:
        return "(no body)"
    if looks_like_html_fragment(s):
        s = _strip_common_email_html_boilerplate(s)
        s = html_to_plain_text_for_mime(s)
    s = _trim_signature_plain(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s if s else "(no body)"


@dataclass(frozen=True)
class _ParsedGmailMessage:
    provider_message_id: str
    provider_thread_id: str
    internal_dt: datetime
    subject: str
    from_email: str
    to_email: str
    body: str
    from_addresses: frozenset[str]
    rfc_message_id: str | None


def _parse_gmail_full(json_msg: dict[str, object]) -> _ParsedGmailMessage | None:
    mid = str(json_msg.get("id") or "").strip()
    if not mid:
        return None
    tid = str(json_msg.get("threadId") or "").strip()
    ms_raw = json_msg.get("internalDate")
    try:
        ms = int(str(ms_raw)) if ms_raw is not None else 0
    except (TypeError, ValueError):
        ms = 0
    internal_dt = datetime.utcfromtimestamp(ms / 1000.0) if ms else datetime.utcnow()

    payload = json_msg.get("payload")
    headers_raw = payload.get("headers") if isinstance(payload, dict) else None
    hmap = _header_map(headers_raw if isinstance(headers_raw, list) else [])

    subj = (hmap.get("subject") or "").strip() or "(no subject)"
    from_hdr = hmap.get("from")
    to_hdr = hmap.get("to")
    from_email = _first_address(from_hdr)
    to_email = _first_address(to_hdr)
    body = _normalize_imported_message_body(_raw_body_from_payload(payload if isinstance(payload, dict) else None))
    from_set = frozenset(_addresses_from_header(from_hdr))
    rfc_mid = normalize_rfc_message_id_header(hmap.get("message-id"))
    return _ParsedGmailMessage(
        provider_message_id=mid,
        provider_thread_id=tid,
        internal_dt=internal_dt,
        subject=subj,
        from_email=from_email,
        to_email=to_email,
        body=body,
        from_addresses=from_set,
        rfc_message_id=rfc_mid,
    )


def _our_address_set(access_token: str) -> set[str]:
    profile = _norm(gmail_profile_email(access_token))
    out = {profile} if profile else set()
    for a in list_send_as_emails(access_token):
        n = _norm(a)
        if n:
            out.add(n)
    return out


def import_inbox_and_sent_six_months(
    db: Session,
    run_id: int,
    email_normalized: str,
    *,
    access_token: str | None = None,
) -> dict:
    """
    List Gmail (inbox OR sent, newer_than:6m, to/from address), persist new messages.
    Sets gmail_inbox_imported_at on the contact group after a full successful pass.
    """
    require_gmail_configured()
    if not get_run(db, run_id):
        raise ValueError("Run not found")

    key = _norm(email_normalized)
    if not key:
        raise ValueError("Invalid email")

    raw = list_contacts_raw_by_run(db, run_id)
    groups = group_contacts_by_email(raw)
    group = groups.get(key)
    if not group:
        raise ValueError("No contact with this email in this run")

    if not all((c.gmail_history_status or "") == GMAIL_HISTORY_YES for c in group):
        raise ValueError("Gmail history must be «History detected» before import.")
    if any(c.gmail_inbox_imported_at is not None for c in group):
        raise ValueError("This address was already imported.")

    token = access_token or refresh_access_token()
    our_emails = _our_address_set(token)

    contact_id = min(c.id for c in group)
    q = f"newer_than:6m (in:inbox OR in:sent) (to:{key} OR from:{key})"
    try:
        refs = gmail_list_message_refs_paginated(token, q)
    except GmailOAuthError:
        raise

    parsed: list[_ParsedGmailMessage] = []
    for i, ref in enumerate(refs):
        mid = str(ref.get("id") or "").strip()
        if not mid:
            continue
        try:
            raw_msg = gmail_get_message_full(token, mid)
        except GmailOAuthError:
            raise
        row = _parse_gmail_full(raw_msg)
        if row:
            parsed.append(row)
        if i and i % 25 == 0:
            time.sleep(0.15)
        else:
            time.sleep(0.05)

    parsed.sort(key=lambda r: r.internal_dt)

    imported = 0
    skipped_existing = 0
    for row in parsed:
        if get_email_message_by_provider_id(db, row.provider_message_id):
            skipped_existing += 1
            continue

        is_out = bool(row.from_addresses & our_emails)
        direction = "outbound" if is_out else "inbound"

        g_tid = row.provider_thread_id
        if not g_tid:
            g_tid = row.provider_message_id

        thread = find_email_thread_by_run_contact_gmail(db, run_id, contact_id, g_tid)
        if thread is None:
            thread = create_email_thread(
                db,
                run_id,
                contact_id,
                draft_id=None,
                subject=row.subject,
                provider_thread_id=g_tid,
                status="open",
                last_message_at=row.internal_dt,
            )
        else:
            bump_email_thread_last_message_at(db, thread, row.internal_dt)

        create_email_message(
            db=db,
            thread_id=thread.id,
            run_id=run_id,
            contact_id=contact_id,
            draft_id=None,
            direction=direction,
            from_email=row.from_email or None,
            to_email=row.to_email or None,
            subject=row.subject,
            body=row.body,
            provider_message_id=row.provider_message_id,
            rfc_message_id=row.rfc_message_id,
        )
        imported += 1

    imported_at = datetime.utcnow()
    apply_gmail_inbox_imported_at(db, group, imported_at=imported_at)
    return {
        "email_normalized": key,
        "listed": len(refs),
        "imported": imported,
        "skipped_existing": skipped_existing,
    }
