from datetime import datetime

from sqlalchemy.orm import Session

from app.models.email_draft import EmailDraft
from app.repositories.contact_repo import get_contact
from app.utils.attached_asset_ids import normalize_attached_asset_ids


def create_email_draft(
    db: Session,
    run_id: int,
    contact_id: int,
    company: str | None,
    to_email: str | None,
    subject: str,
    body: str,
    status: str = "draft",
    review_status: str = "pending",
    review_notes: str | None = None,
) -> EmailDraft:
    draft = EmailDraft(
        run_id=run_id,
        contact_id=contact_id,
        company=company,
        to_email=to_email,
        subject=subject,
        body=body,
        status=status,
        review_status=review_status,
        review_notes=review_notes,
        tracking_status="draft",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def bulk_create_email_drafts(db: Session, rows: list[dict]) -> list[EmailDraft]:
    drafts = [EmailDraft(**row) for row in rows]
    db.add_all(drafts)
    db.commit()

    for draft in drafts:
        db.refresh(draft)

    return drafts


def list_email_drafts_by_run(db: Session, run_id: int) -> list[EmailDraft]:
    return (
        db.query(EmailDraft)
        .filter(EmailDraft.run_id == run_id)
        .order_by(EmailDraft.id.asc())
        .all()
    )


def list_sendable_email_drafts_by_run(db: Session, run_id: int) -> list[EmailDraft]:
    """Approved/edited, sendable state, non-empty recipient; `failed` allows retry."""
    return (
        db.query(EmailDraft)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.review_status.in_(["approved", "edited"]),
            EmailDraft.status.in_(["draft", "failed"]),
            EmailDraft.to_email.isnot(None),
            EmailDraft.to_email != "",
        )
        .order_by(EmailDraft.id.asc())
        .all()
    )


def list_sendable_replacement_email_drafts_by_run(db: Session, run_id: int) -> list[EmailDraft]:
    drafts = (
        db.query(EmailDraft)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.review_status.in_(["approved", "edited"]),
            EmailDraft.status.in_(["draft", "failed"]),
            EmailDraft.to_email.isnot(None),
            EmailDraft.to_email != "",
        )
        .order_by(EmailDraft.id.asc())
        .all()
    )

    result: list[EmailDraft] = []
    for draft in drafts:
        contact = get_contact(db, draft.contact_id)
        if not contact:
            continue
        source_json = contact.source_json or {}
        if source_json.get("source") == "replacement_search":
            result.append(draft)

    return result


def get_email_draft(db: Session, draft_id: int) -> EmailDraft | None:
    return db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()


def find_draft_by_contact_id(db: Session, run_id: int, contact_id: int) -> EmailDraft | None:
    return (
        db.query(EmailDraft)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.contact_id == contact_id,
        )
        .order_by(EmailDraft.id.desc())
        .first()
    )


def delete_email_draft(db: Session, draft: EmailDraft) -> None:
    db.delete(draft)
    db.commit()


def update_email_draft_outreach_regenerate(
    db: Session,
    draft: EmailDraft,
    *,
    subject: str,
    body: str,
    company: str | None,
    to_email: str | None,
) -> EmailDraft:
    """Replace subject/body after Regenerate; same row id. Review resets to pending so the user can Approve again."""
    draft.subject = subject
    draft.body = body
    draft.company = company
    draft.to_email = to_email
    draft.status = "draft"
    draft.tracking_status = "draft"
    draft.review_status = "pending"
    draft.review_notes = None
    draft.reviewed_at = None
    draft.error_message = None
    draft.provider_message_id = None
    draft.thread_id = None
    draft.sent_at = None
    draft.last_event_at = datetime.utcnow()
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def delete_email_drafts_by_run(db: Session, run_id: int) -> int:
    query = db.query(EmailDraft).filter(EmailDraft.run_id == run_id)
    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    return count


def update_email_draft_review(
    db: Session,
    draft: EmailDraft,
    review_status: str,
    review_notes: str | None = None,
) -> EmailDraft:
    draft.review_status = review_status
    draft.review_notes = review_notes
    draft.reviewed_at = datetime.utcnow()
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def bulk_set_attached_assets_for_pending_drafts(
    db: Session,
    run_id: int,
    attached_asset_ids: list[int],
) -> int:
    """Copy normalized asset ids onto every draft in the run still in pending review. Returns count updated."""
    normalized = normalize_attached_asset_ids(attached_asset_ids)
    drafts = (
        db.query(EmailDraft)
        .filter(EmailDraft.run_id == run_id, EmailDraft.review_status == "pending")
        .all()
    )
    for d in drafts:
        d.attached_asset_ids = list(normalized)
        db.add(d)
    if drafts:
        db.commit()
    return len(drafts)


def update_email_draft_fields(
    db: Session,
    draft: EmailDraft,
    subject: str | None = None,
    body: str | None = None,
    review_notes: str | None = None,
    attached_asset_ids: list[int] | None = None,
) -> EmailDraft:
    if subject is not None:
        draft.subject = subject
    if body is not None:
        draft.body = body
    if review_notes is not None:
        draft.review_notes = review_notes
    if attached_asset_ids is not None:
        draft.attached_asset_ids = normalize_attached_asset_ids(attached_asset_ids)

    draft.review_status = "edited"
    draft.reviewed_at = datetime.utcnow()

    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_sending(db: Session, draft: EmailDraft) -> EmailDraft:
    draft.status = "sending"
    draft.tracking_status = "sending"
    draft.last_event_at = datetime.utcnow()
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_sent(
    db: Session,
    draft: EmailDraft,
    provider_message_id: str | None = None,
    thread_id: str | None = None,
) -> EmailDraft:
    draft.status = "sent"
    draft.tracking_status = "sent"
    draft.provider_message_id = provider_message_id
    draft.thread_id = thread_id
    draft.sent_at = datetime.utcnow()
    draft.last_event_at = datetime.utcnow()
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_failed(db: Session, draft: EmailDraft, error_message: str) -> EmailDraft:
    draft.status = "failed"
    draft.tracking_status = "failed"
    draft.error_message = error_message
    draft.last_event_at = datetime.utcnow()
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_replied(db: Session, draft: EmailDraft) -> EmailDraft:
    draft.tracking_status = "replied"
    draft.last_event_at = datetime.utcnow()
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_bounced(
    db: Session,
    draft: EmailDraft,
    error_message: str | None = None,
) -> EmailDraft:
    draft.tracking_status = "bounced"
    draft.last_event_at = datetime.utcnow()
    # Delivery diagnostics live on email_events; avoid surfacing DSN/HTML in human draft review.
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_email_draft_dead_mailbox(
    db: Session,
    draft: EmailDraft,
    error_message: str | None = None,
) -> EmailDraft:
    draft.tracking_status = "dead_mailbox"
    draft.last_event_at = datetime.utcnow()
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft
