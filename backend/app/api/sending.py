from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.email_draft_repo import get_email_draft
from app.repositories.run_repo import get_run
from app.services.email_sender import send_approved_drafts_for_run, send_one_draft
from app.services.run_summary_service import get_run_summary

router = APIRouter(prefix="/sending", tags=["sending"])


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


@router.get("/runs/{run_id}/summary")
def run_summary_route(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return get_run_summary(db, run_id)
