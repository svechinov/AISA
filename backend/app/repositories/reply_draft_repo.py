from datetime import datetime

from sqlalchemy.orm import Session

from app.models.reply_draft import ReplyDraft
from app.repositories.draft_attachment_repo import replace_reply_draft_assets
from app.utils.attached_asset_ids import normalize_attached_asset_ids


def create_reply_draft(
    db: Session,
    run_id: int,
    thread_id: int,
    contact_id: int,
    reply_type: str,
    to_email: str | None,
    subject: str,
    body: str,
    status: str = "draft",
    review_status: str = "pending",
    review_notes: str | None = None,
) -> ReplyDraft:
    draft = ReplyDraft(
        run_id=run_id,
        thread_id=thread_id,
        contact_id=contact_id,
        reply_type=reply_type,
        to_email=to_email,
        subject=subject,
        body=body,
        status=status,
        review_status=review_status,
        review_notes=review_notes,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def get_reply_draft(db: Session, draft_id: int) -> ReplyDraft | None:
    return db.query(ReplyDraft).filter(ReplyDraft.id == draft_id).first()


def list_reply_drafts_by_run(db: Session, run_id: int) -> list[ReplyDraft]:
    return (
        db.query(ReplyDraft)
        .filter(ReplyDraft.run_id == run_id)
        .order_by(ReplyDraft.id.desc())
        .all()
    )


def list_reply_drafts_by_thread(db: Session, thread_id: int) -> list[ReplyDraft]:
    return (
        db.query(ReplyDraft)
        .filter(ReplyDraft.thread_id == thread_id)
        .order_by(ReplyDraft.id.desc())
        .all()
    )


def find_reply_draft_by_thread_and_type(
    db: Session,
    thread_id: int,
    reply_type: str,
) -> ReplyDraft | None:
    return (
        db.query(ReplyDraft)
        .filter(
            ReplyDraft.thread_id == thread_id,
            ReplyDraft.reply_type == reply_type,
        )
        .order_by(ReplyDraft.id.desc())
        .first()
    )


def update_reply_draft_review(
    db: Session,
    draft: ReplyDraft,
    review_status: str,
    review_notes: str | None = None,
) -> ReplyDraft:
    draft.review_status = review_status
    draft.review_notes = review_notes
    draft.reviewed_at = datetime.utcnow()
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def update_reply_draft_fields(
    db: Session,
    draft: ReplyDraft,
    subject: str | None = None,
    body: str | None = None,
    review_notes: str | None = None,
    attached_asset_ids: list[int] | None = None,
) -> ReplyDraft:
    if subject is not None:
        draft.subject = subject
    if body is not None:
        draft.body = body
    if review_notes is not None:
        draft.review_notes = review_notes
    if attached_asset_ids is not None:
        norm = normalize_attached_asset_ids(attached_asset_ids)
        replace_reply_draft_assets(db, draft.id, norm)
        draft.attached_asset_ids = []

    draft.review_status = "edited"
    draft.reviewed_at = datetime.utcnow()

    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_reply_draft_sending(db: Session, draft: ReplyDraft) -> ReplyDraft:
    draft.status = "sending"
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_reply_draft_sent(
    db: Session,
    draft: ReplyDraft,
    provider_message_id: str | None = None,
) -> ReplyDraft:
    draft.status = "sent"
    draft.provider_message_id = provider_message_id
    draft.sent_at = datetime.utcnow()
    draft.error_message = None
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def mark_reply_draft_failed(db: Session, draft: ReplyDraft, error_message: str) -> ReplyDraft:
    draft.status = "failed"
    draft.error_message = error_message
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft
