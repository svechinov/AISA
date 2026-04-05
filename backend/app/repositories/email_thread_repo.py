from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread
from app.repositories.email_draft_repo import list_email_drafts_by_run


def _normalize_subject_for_thread_draft_match(s: str | None) -> str:
    """Strip Re:/RE: chains and collapse whitespace for comparing thread subject to sent draft subject."""
    t = " ".join((s or "").strip().lower().split())
    while t.startswith("re:"):
        t = t[3:].lstrip()
        t = " ".join(t.split())
    return t


def _norm_email_addr(s: str | None) -> str:
    return (s or "").strip().lower()


def find_email_thread_by_run_contact_gmail(
    db: Session,
    run_id: int,
    contact_id: int,
    provider_thread_id: str,
) -> EmailThread | None:
    if not provider_thread_id:
        return None
    return (
        db.query(EmailThread)
        .filter(
            EmailThread.run_id == run_id,
            EmailThread.contact_id == contact_id,
            EmailThread.provider_thread_id == provider_thread_id,
        )
        .first()
    )


def create_email_thread(
    db: Session,
    run_id: int,
    contact_id: int,
    draft_id: int | None,
    subject: str,
    provider_thread_id: str | None = None,
    status: str = "open",
    *,
    last_message_at: datetime | None = None,
) -> EmailThread:
    thread = EmailThread(
        run_id=run_id,
        contact_id=contact_id,
        draft_id=draft_id,
        subject=subject,
        provider_thread_id=provider_thread_id,
        status=status,
        last_message_at=last_message_at or datetime.utcnow(),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def get_email_thread(db: Session, thread_id: int) -> EmailThread | None:
    return db.query(EmailThread).filter(EmailThread.id == thread_id).first()


def get_email_thread_by_draft_id(db: Session, draft_id: int) -> EmailThread | None:
    return (
        db.query(EmailThread)
        .filter(EmailThread.draft_id == draft_id)
        .order_by(EmailThread.id.desc())
        .first()
    )


def find_email_thread_by_provider_thread_id(db: Session, provider_thread_id: str) -> EmailThread | None:
    return (
        db.query(EmailThread)
        .filter(EmailThread.provider_thread_id == provider_thread_id)
        .first()
    )


def list_email_threads_by_run(db: Session, run_id: int) -> list[EmailThread]:
    return (
        db.query(EmailThread)
        .filter(EmailThread.run_id == run_id)
        .order_by(EmailThread.id.desc())
        .all()
    )


def list_email_threads_by_run_paginated(
    db: Session,
    run_id: int,
    *,
    limit: int,
    offset: int,
    q: str | None,
) -> tuple[list[EmailThread], int]:
    """Same sort as list_email_threads_by_run (id desc). Optional search on subject and provider_thread_id."""
    qy = db.query(EmailThread).filter(EmailThread.run_id == run_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        qy = qy.filter(
            or_(
                EmailThread.subject.ilike(like),
                EmailThread.provider_thread_id.ilike(like),
            )
        )
    total = int(qy.count() or 0)
    rows = (
        qy.order_by(EmailThread.id.desc()).offset(max(0, offset)).limit(max(1, limit)).all()
    )
    return rows, total


def _resolve_thread_outbound_draft_id_in_memory(
    thread: EmailThread,
    msgs: list[EmailMessage],
    contacts_by_id: dict[int, Contact],
    drafts_list: list[EmailDraft],
) -> int | None:
    """Shared logic for resolve_thread_outbound_draft_id / bulk (no DB queries).

    Order: outbound message ``draft_id`` → Gmail ``thread_id`` (same contact, else same run) →
    ``provider_message_id`` (same contact, else same run) → outbound ``To:`` vs sent drafts →
    **contact.company** vs **draft.company** (sent, same run) → normalized subject (same run).
    """
    if thread.draft_id:
        return thread.draft_id

    msgs_out = sorted(
        [m for m in msgs if m.direction == "outbound"],
        key=lambda m: m.id,
    )
    for m in msgs_out:
        if m.draft_id:
            return int(m.draft_id)

    g_tid = (thread.provider_thread_id or "").strip()
    if g_tid:
        cand = [
            d
            for d in drafts_list
            if d.run_id == thread.run_id
            and d.contact_id == thread.contact_id
            and (d.thread_id or "") == g_tid
        ]
        if cand:
            return int(max(cand, key=lambda d: d.id).id)
        cand = [
            d
            for d in drafts_list
            if d.run_id == thread.run_id and (d.thread_id or "") == g_tid
        ]
        if cand:
            return int(max(cand, key=lambda d: d.id).id)

    mids = [m.provider_message_id for m in msgs_out if m.provider_message_id]
    if mids:
        cand = [
            d
            for d in drafts_list
            if d.run_id == thread.run_id
            and d.contact_id == thread.contact_id
            and d.provider_message_id in mids
        ]
        if cand:
            return int(max(cand, key=lambda d: d.id).id)
        cand = [
            d
            for d in drafts_list
            if d.run_id == thread.run_id and d.provider_message_id in mids
        ]
        if cand:
            return int(max(cand, key=lambda d: d.id).id)

    out_to_first: str | None = None
    for m in msgs_out:
        if m.to_email:
            out_to_first = m.to_email
            break
    if out_to_first:
        to_n = _norm_email_addr(out_to_first)
        if to_n:
            sent = sorted(
                [d for d in drafts_list if d.run_id == thread.run_id and d.status == "sent"],
                key=lambda d: -d.id,
            )
            matches = [x for x in sent if _norm_email_addr(x.to_email) == to_n]
            if len(matches) == 1:
                return int(matches[0].id)
            if len(matches) > 1:
                pref = [x for x in matches if x.contact_id == thread.contact_id]
                if len(pref) == 1:
                    return int(pref[0].id)
                return int(matches[0].id)

    c_row = contacts_by_id.get(thread.contact_id)
    if c_row and (c_row.company or "").strip():
        co_norm = " ".join((c_row.company or "").strip().lower().split())
        sent_co = sorted(
            [d for d in drafts_list if d.run_id == thread.run_id and d.status == "sent"],
            key=lambda d: -d.id,
        )
        co_matches = [
            x
            for x in sent_co
            if " ".join((x.company or "").strip().lower().split()) == co_norm
        ]
        if len(co_matches) == 1:
            return int(co_matches[0].id)
        if len(co_matches) > 1:
            em = _norm_email_addr(c_row.email)
            pref = [x for x in co_matches if _norm_email_addr(x.to_email) == em]
            if len(pref) == 1:
                return int(pref[0].id)

    want_sub = _normalize_subject_for_thread_draft_match(thread.subject)
    if want_sub:
        candidates = [d for d in drafts_list if d.run_id == thread.run_id]
        candidates.sort(
            key=lambda d: (
                0 if d.contact_id == thread.contact_id else 1,
                0 if d.status == "sent" else 1,
                -d.id,
            )
        )
        for d in candidates:
            if _normalize_subject_for_thread_draft_match(d.subject) == want_sub:
                return int(d.id)

    return None


def resolve_thread_outbound_draft_id(db: Session, thread: EmailThread) -> int | None:
    """When email_threads.draft_id is null (e.g. thread created by Gmail import), infer the outreach draft."""
    if thread.draft_id:
        return thread.draft_id
    drafts_list = list_email_drafts_by_run(db, thread.run_id)
    msgs = db.query(EmailMessage).filter(EmailMessage.thread_id == thread.id).all()
    c_row = db.query(Contact).filter(Contact.id == thread.contact_id).first()
    contacts_by_id = {c_row.id: c_row} if c_row else {}
    return _resolve_thread_outbound_draft_id_in_memory(thread, msgs, contacts_by_id, drafts_list)


def bulk_resolve_thread_outbound_draft_ids(
    db: Session,
    run_id: int,
    threads: list[EmailThread],
    contacts_by_id: dict[int, Contact],
    drafts_list: list[EmailDraft],
) -> dict[int, int | None]:
    """Same as ``resolve_thread_outbound_draft_id`` per thread, one bulk load of messages + in-memory resolve."""
    if not threads:
        return {}
    thread_ids = [t.id for t in threads]
    all_msgs = (
        db.query(EmailMessage)
        .filter(EmailMessage.thread_id.in_(thread_ids), EmailMessage.run_id == run_id)
        .all()
    )
    by_thread: dict[int, list[EmailMessage]] = {}
    for m in all_msgs:
        by_thread.setdefault(m.thread_id, []).append(m)
    out: dict[int, int | None] = {}
    for t in threads:
        msgs = by_thread.get(t.id, [])
        out[t.id] = _resolve_thread_outbound_draft_id_in_memory(
            t, msgs, contacts_by_id, drafts_list
        )
    return out


def update_email_thread_status(db: Session, thread: EmailThread, status: str) -> EmailThread:
    thread.status = status
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def touch_email_thread(db: Session, thread: EmailThread) -> EmailThread:
    thread.last_message_at = datetime.utcnow()
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def bump_email_thread_last_message_at(db: Session, thread: EmailThread, at: datetime) -> EmailThread:
    cur = thread.last_message_at
    if cur is None or at > cur:
        thread.last_message_at = at
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread
