import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_draft_repo import get_email_draft
from app.repositories.run_repo import get_run
from app.services.email_sender import (
    mock_send_first_approved_draft_preview,
    send_approved_drafts_for_run,
    send_one_draft,
)
from app.services.gmail_oauth import GmailOAuthError
from app.services.run_summary_service import get_run_summary

router = APIRouter(prefix="/sending", tags=["sending"])
_log = logging.getLogger(__name__)


@router.post("/drafts/{draft_id}/send")
def send_single_draft_route(draft_id: int, db: Session = Depends(get_db)):
    if not get_email_draft(db, draft_id):
        raise HTTPException(status_code=404, detail="Email draft not found")
    try:
        return send_one_draft(db, draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/runs/{run_id}/send")
def send_run_drafts_route(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return send_approved_drafts_for_run(db, run_id)


# MOCK_SEND_PREVIEW — temporary; remove this route when deleting the feature.
@router.post("/runs/{run_id}/mock-send-preview")
def mock_send_preview_route(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        return mock_send_first_approved_draft_preview(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        _log.exception("mock-send-preview failed run_id=%s", run_id)
        raise HTTPException(
            status_code=400,
            detail=f"Send test copy failed ({type(e).__name__}): {e}",
        ) from e


@router.get("/runs/{run_id}/summary")
def run_summary_route(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return get_run_summary(db, run_id)
