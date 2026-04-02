from datetime import datetime

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_message import EmailMessage
from app.models.email_thread import EmailThread


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


def resolve_thread_outbound_draft_id(db: Session, thread: EmailThread) -> int | None:
    """When email_threads.draft_id is null (e.g. thread created by Gmail import), infer the outreach draft.

    Order: outbound message ``draft_id`` → Gmail ``thread_id`` (same contact, else same run) →
    ``provider_message_id`` (same contact, else same run) → outbound ``To:`` vs sent drafts →
    **contact.company** vs **draft.company** (sent, same run) → normalized subject (same run).
    """
    if thread.draft_id:
        return thread.draft_id

    msg_with_draft = (
        db.query(EmailMessage)
        .filter(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
            EmailMessage.draft_id.isnot(None),
        )
        .order_by(EmailMessage.id.asc())
        .first()
    )
    if msg_with_draft and msg_with_draft.draft_id:
        return int(msg_with_draft.draft_id)

    g_tid = (thread.provider_thread_id or "").strip()
    if g_tid:
        d = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.run_id == thread.run_id,
                EmailDraft.contact_id == thread.contact_id,
                EmailDraft.thread_id == g_tid,
            )
            .order_by(EmailDraft.id.desc())
            .first()
        )
        if d:
            return int(d.id)
        d = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.run_id == thread.run_id,
                EmailDraft.thread_id == g_tid,
            )
            .order_by(EmailDraft.id.desc())
            .first()
        )
        if d:
            return int(d.id)

    mids = [
        row[0]
        for row in db.query(EmailMessage.provider_message_id)
        .filter(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
            EmailMessage.provider_message_id.isnot(None),
        )
        .all()
        if row[0]
    ]
    if mids:
        d = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.run_id == thread.run_id,
                EmailDraft.contact_id == thread.contact_id,
                EmailDraft.provider_message_id.in_(mids),
            )
            .order_by(EmailDraft.id.desc())
            .first()
        )
        if d:
            return int(d.id)
        d = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.run_id == thread.run_id,
                EmailDraft.provider_message_id.in_(mids),
            )
            .order_by(EmailDraft.id.desc())
            .first()
        )
        if d:
            return int(d.id)

    out_to_row = (
        db.query(EmailMessage.to_email)
        .filter(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
            EmailMessage.to_email.isnot(None),
        )
        .order_by(EmailMessage.id.asc())
        .first()
    )
    if out_to_row and out_to_row[0]:
        to_n = _norm_email_addr(out_to_row[0])
        if to_n:
            sent = (
                db.query(EmailDraft)
                .filter(
                    EmailDraft.run_id == thread.run_id,
                    EmailDraft.status == "sent",
                )
                .order_by(EmailDraft.id.desc())
                .all()
            )
            matches = [x for x in sent if _norm_email_addr(x.to_email) == to_n]
            if len(matches) == 1:
                return int(matches[0].id)
            if len(matches) > 1:
                pref = [x for x in matches if x.contact_id == thread.contact_id]
                if len(pref) == 1:
                    return int(pref[0].id)
                return int(matches[0].id)

    c_row = db.query(Contact).filter(Contact.id == thread.contact_id).first()
    if c_row and (c_row.company or "").strip():
        co_norm = " ".join((c_row.company or "").strip().lower().split())
        sent_co = (
            db.query(EmailDraft)
            .filter(
                EmailDraft.run_id == thread.run_id,
                EmailDraft.status == "sent",
            )
            .order_by(EmailDraft.id.desc())
            .all()
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
        candidates = (
            db.query(EmailDraft)
            .filter(EmailDraft.run_id == thread.run_id)
            .order_by(EmailDraft.id.desc())
            .all()
        )
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
