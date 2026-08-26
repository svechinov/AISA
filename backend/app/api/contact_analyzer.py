import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.run_repo import get_run
from app.schemas.contact_analyzer import (
    ContactAnalyzerImportInboxBody,
    ContactAnalyzerImportInboxResponse,
    ContactAnalyzerListResponse,
    ContactAnalyzerVerifyAllResponse,
    ContactAnalyzerVerifyBody,
    ContactAnalyzerVerifyResponse,
)
from app.services.gmail_inbox_import_service import import_inbox_and_sent_six_months
from app.services.gmail_oauth import GmailOAuthError
from app.services.contact_gmail_history_service import (
    list_contact_analyzer_rows,
    verify_all_unverified_emails,
    verify_run_email,
)

router = APIRouter(prefix="/runs", tags=["contact-analyzer"])
_log = logging.getLogger(__name__)


@router.get("/{run_id}/contact-analyzer", response_model=ContactAnalyzerListResponse)
def get_contact_analyzer(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    rows = list_contact_analyzer_rows(db, run_id)
    return ContactAnalyzerListResponse(run_id=run_id, rows=rows)


@router.post("/{run_id}/contact-analyzer/verify", response_model=ContactAnalyzerVerifyResponse)
def post_verify_one(run_id: int, body: ContactAnalyzerVerifyBody, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        out = verify_run_email(db, run_id, body.email_normalized.strip().lower())
    except GmailOAuthError as e:
        _log.exception("contact-analyzer verify Gmail error")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ContactAnalyzerVerifyResponse(
        email_normalized=out["email_normalized"],
        gmail_history_status=out["gmail_history_status"],
    )


@router.post("/{run_id}/contact-analyzer/verify-all", response_model=ContactAnalyzerVerifyAllResponse)
def post_verify_all(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        out = verify_all_unverified_emails(db, run_id)
    except GmailOAuthError as e:
        _log.exception("contact-analyzer verify-all Gmail error")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ContactAnalyzerVerifyAllResponse(**out)


@router.post(
    "/{run_id}/contact-analyzer/import-inbox",
    response_model=ContactAnalyzerImportInboxResponse,
)
def post_import_inbox(run_id: int, body: ContactAnalyzerImportInboxBody, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        out = import_inbox_and_sent_six_months(db, run_id, body.email_normalized.strip().lower())
    except GmailOAuthError as e:
        _log.exception("contact-analyzer import-inbox Gmail error")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return ContactAnalyzerImportInboxResponse(**out)
