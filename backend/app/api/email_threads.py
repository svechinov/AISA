from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_message_repo import list_email_messages_by_run, list_email_messages_by_thread
from app.repositories.email_thread_repo import (
    get_email_thread,
    list_email_threads_by_run,
    resolve_thread_outbound_draft_id,
)
from app.schemas.email_message import EmailMessageRead
from app.schemas.email_thread import EmailThreadRead, ThreadDeliveryLlmAnalyzeResponse
from app.services.email_tracking_service import register_manual_bounce, register_manual_dead_mailbox
from app.services.thread_delivery_llm_service import analyze_thread_delivery_llm

router = APIRouter(prefix="/email-threads", tags=["email-threads"])


def _thread_read_with_effective_draft(db: Session, t) -> EmailThreadRead:
    eff = t.draft_id or resolve_thread_outbound_draft_id(db, t)
    base = EmailThreadRead.model_validate(t)
    return base.model_copy(update={"effective_draft_id": eff})


@router.get("/run/{run_id}/messages", response_model=list[EmailMessageRead])
def list_messages_for_run_route(run_id: int, db: Session = Depends(get_db)):
    return list_email_messages_by_run(db, run_id)


@router.get("/run/{run_id}", response_model=list[EmailThreadRead])
def list_threads_for_run(run_id: int, db: Session = Depends(get_db)):
    return [_thread_read_with_effective_draft(db, t) for t in list_email_threads_by_run(db, run_id)]


@router.get("/{thread_id}/messages", response_model=list[EmailMessageRead])
def list_thread_messages_route(thread_id: int, db: Session = Depends(get_db)):
    return list_email_messages_by_thread(db, thread_id)


@router.post("/{thread_id}/analyze-delivery-llm", response_model=ThreadDeliveryLlmAnalyzeResponse)
def analyze_thread_delivery_llm_route(thread_id: int, db: Session = Depends(get_db)):
    """On-demand: LLM reads the thread and guesses bounce vs dead mailbox vs none (does not change DB)."""
    if not get_email_thread(db, thread_id):
        raise HTTPException(status_code=404, detail="Thread not found")
    out = analyze_thread_delivery_llm(db, thread_id)
    if out.get("error") == "thread_not_found":
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadDeliveryLlmAnalyzeResponse(
        delivery_issue=str(out.get("delivery_issue") or "unclear"),
        confidence=str(out.get("confidence") or "low"),
        reason=str(out.get("reason") or ""),
        error=out.get("error"),
    )


@router.post("/{thread_id}/mark-bounced")
def mark_thread_bounced_manual_route(thread_id: int, db: Session = Depends(get_db)):
    """Irreversible: marks the linked outbound draft/contact as bounced (human override)."""
    t = get_email_thread(db, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    draft_id = t.draft_id or resolve_thread_outbound_draft_id(db, t)
    if not draft_id:
        raise HTTPException(
            status_code=400,
            detail="Thread has no linked outbound draft — cannot set delivery state.",
        )
    if not t.draft_id:
        t.draft_id = draft_id
        db.add(t)
        db.commit()
        db.refresh(t)
    try:
        return register_manual_bounce(
            db,
            draft_id,
            payload_json={"source": "manual_thread_ui", "thread_id": thread_id},
            error_message="Marked as bounced (manual)",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{thread_id}/mark-dead-mailbox")
def mark_thread_dead_mailbox_manual_route(thread_id: int, db: Session = Depends(get_db)):
    """Irreversible: marks the linked outbound draft/contact as dead mailbox (human override)."""
    t = get_email_thread(db, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    draft_id = t.draft_id or resolve_thread_outbound_draft_id(db, t)
    if not draft_id:
        raise HTTPException(
            status_code=400,
            detail="Thread has no linked outbound draft — cannot set delivery state.",
        )
    if not t.draft_id:
        t.draft_id = draft_id
        db.add(t)
        db.commit()
        db.refresh(t)
    try:
        return register_manual_dead_mailbox(
            db,
            draft_id,
            payload_json={"source": "manual_thread_ui", "thread_id": thread_id},
            error_message="Marked as dead mailbox (manual)",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{thread_id}", response_model=EmailThreadRead)
def get_thread_route(thread_id: int, db: Session = Depends(get_db)):
    t = get_email_thread(db, thread_id)
    if not t:
        raise HTTPException(status_code=404, detail="Thread not found")
    return _thread_read_with_effective_draft(db, t)
