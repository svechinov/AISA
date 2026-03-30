from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_draft_repo import get_email_draft
from app.schemas.tracking import TrackingEventCreate
from app.services.email_tracking_service import (
    register_bounced_event,
    register_dead_mailbox_event,
    register_replied_event,
)

router = APIRouter(prefix="/tracking", tags=["tracking"])


def _parse_tracking(body: dict) -> TrackingEventCreate:
    return TrackingEventCreate.model_validate(body or {})


@router.post("/drafts/{draft_id}/mock-reply")
def mock_reply_route(
    draft_id: int,
    db: Session = Depends(get_db),
    body: dict = Body(default_factory=dict),
):
    if not get_email_draft(db, draft_id):
        raise HTTPException(status_code=404, detail="Email draft not found")
    p = _parse_tracking(body)
    try:
        return register_replied_event(
            db=db,
            draft_id=draft_id,
            payload_json=p.payload_json,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/drafts/{draft_id}/mock-bounce")
def mock_bounce_route(
    draft_id: int,
    db: Session = Depends(get_db),
    body: dict = Body(default_factory=dict),
):
    if not get_email_draft(db, draft_id):
        raise HTTPException(status_code=404, detail="Email draft not found")
    p = _parse_tracking(body)
    try:
        return register_bounced_event(
            db=db,
            draft_id=draft_id,
            payload_json=p.payload_json,
            error_message=p.error_message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/drafts/{draft_id}/mock-dead-mailbox")
def mock_dead_mailbox_route(
    draft_id: int,
    db: Session = Depends(get_db),
    body: dict = Body(default_factory=dict),
):
    if not get_email_draft(db, draft_id):
        raise HTTPException(status_code=404, detail="Email draft not found")
    p = _parse_tracking(body)
    try:
        return register_dead_mailbox_event(
            db=db,
            draft_id=draft_id,
            payload_json=p.payload_json,
            error_message=p.error_message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
