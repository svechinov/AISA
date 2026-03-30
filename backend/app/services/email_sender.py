from sqlalchemy.orm import Session

from app.repositories.email_draft_repo import (
    get_email_draft,
    list_sendable_email_drafts_by_run,
    mark_email_draft_failed,
    mark_email_draft_sent,
    mark_email_draft_sending,
)
from app.repositories.run_repo import get_run
from app.repositories.email_event_repo import create_email_event
from app.repositories.email_message_repo import create_email_message
from app.repositories.email_thread_repo import (
    create_email_thread,
    get_email_thread_by_draft_id,
    touch_email_thread,
)
from app.services.email_provider import send_email_via_provider


def send_one_draft(db: Session, draft_id: int) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    if draft.review_status not in {"approved", "edited"}:
        raise ValueError("Draft is not approved")

    if not (draft.to_email or "").strip():
        raise ValueError("Missing recipient email")

    if draft.status not in {"draft", "failed"}:
        raise ValueError("Draft is not sendable in current state")

    run = get_run(db, draft.run_id)
    if run and run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")

    mark_email_draft_sending(db, draft)

    create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="queued",
        payload_json={},
    )

    try:
        result = send_email_via_provider(
            to_email=draft.to_email.strip(),
            subject=draft.subject,
            body=draft.body,
        )

        mark_email_draft_sent(
            db,
            draft,
            provider_message_id=result.get("provider_message_id"),
            thread_id=result.get("thread_id"),
        )

        create_email_event(
            db=db,
            run_id=draft.run_id,
            draft_id=draft.id,
            contact_id=draft.contact_id,
            event_type="sent",
            provider_message_id=result.get("provider_message_id"),
            payload_json=result,
        )

        draft = get_email_draft(db, draft.id)
        existing_thread = get_email_thread_by_draft_id(db, draft.id)
        thread = existing_thread
        if not thread:
            thread = create_email_thread(
                db=db,
                run_id=draft.run_id,
                contact_id=draft.contact_id,
                draft_id=draft.id,
                subject=draft.subject,
                provider_thread_id=result.get("thread_id"),
                status="open",
            )

        create_email_message(
            db=db,
            thread_id=thread.id,
            run_id=draft.run_id,
            contact_id=draft.contact_id,
            draft_id=draft.id,
            direction="outbound",
            from_email=None,
            to_email=draft.to_email,
            subject=draft.subject,
            body=draft.body,
            provider_message_id=result.get("provider_message_id"),
        )

        touch_email_thread(db, thread)

        return {
            "draft_id": draft.id,
            "status": "sent",
            "provider_message_id": result.get("provider_message_id"),
        }

    except Exception as e:  # noqa: BLE001
        mark_email_draft_failed(db, draft, str(e))

        create_email_event(
            db=db,
            run_id=draft.run_id,
            draft_id=draft.id,
            contact_id=draft.contact_id,
            event_type="failed",
            error_message=str(e),
            payload_json={},
        )

        return {
            "draft_id": draft.id,
            "status": "failed",
            "error": str(e),
        }


def send_approved_drafts_for_run(db: Session, run_id: int) -> dict:
    run = get_run(db, run_id)
    if run and run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")

    drafts = list_sendable_email_drafts_by_run(db, run_id)

    results = []
    for draft in drafts:
        results.append(send_one_draft(db, draft.id))

    return {
        "run_id": run_id,
        "attempted": len(drafts),
        "results": results,
    }
