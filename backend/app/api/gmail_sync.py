"""Manual + status for Gmail thread / bounce sync (background loop optional via GMAIL_SYNC_INTERVAL_SECONDS)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.repositories.run_repo import get_run
from app.services.contact_gmail_history_service import require_gmail_configured
from app.services.gmail_oauth import GmailOAuthError, google_client_configured, google_refresh_token_value
from app.services.gmail_tracking_sync_service import (
    sync_bounce_notifications,
    sync_gmail_all_open_runs,
    sync_gmail_for_run,
    sync_thread_messages_for_run,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail-sync", tags=["gmail-sync"])


@router.get("/status")
def gmail_sync_status() -> dict:
    return {
        "background_interval_seconds": int(getattr(settings, "GMAIL_SYNC_INTERVAL_SECONDS", 0) or 0),
        "gmail_configured": bool(google_client_configured() and google_refresh_token_value()),
    }


@router.post("/run/{run_id}")
def gmail_sync_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        require_gmail_configured()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return sync_gmail_for_run(db, run_id)
    except GmailOAuthError as e:
        _log.exception("gmail sync run_id=%s", run_id)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/runs/all-open")
def gmail_sync_all_open_runs(db: Session = Depends(get_db)) -> dict:
    try:
        require_gmail_configured()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return sync_gmail_all_open_runs(db)
    except GmailOAuthError as e:
        _log.exception("gmail sync all open runs")
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/bounces")
def gmail_sync_bounces_only(db: Session = Depends(get_db)) -> dict:
    try:
        require_gmail_configured()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return sync_bounce_notifications(db)
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/run/{run_id}/threads-only")
def gmail_sync_threads_only(run_id: int, db: Session = Depends(get_db)) -> dict:
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        require_gmail_configured()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return sync_thread_messages_for_run(db, run_id)
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
