import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.repositories.email_draft_repo import get_email_draft, list_sendable_email_drafts_by_run
from app.repositories.run_repo import get_run
from app.schemas.run import TotalPerformanceRead
from app.services.email_sender import (
    send_approved_drafts_for_run_in_thread,
    send_one_draft_in_thread,
    validate_outbound_draft_sendable,
)
from app.services.run_display_service import get_total_performance_global
from app.services.run_summary_service import get_run_summary

router = APIRouter(prefix="/sending", tags=["sending"])
_log = logging.getLogger(__name__)


async def _queue_send_one_draft(draft_id: int) -> None:
    await run_in_threadpool(send_one_draft_in_thread, draft_id)


async def _queue_send_run(run_id: int) -> None:
    await run_in_threadpool(send_approved_drafts_for_run_in_thread, run_id)


@router.get("/global-performance", response_model=TotalPerformanceRead)
def global_performance_route(db: Session = Depends(get_db)):
    """Aggregate sent counts for all runs (all projects); safe path (no clash with /runs/{id})."""
    return TotalPerformanceRead(**get_total_performance_global(db))


@router.post("/drafts/{draft_id}/send", status_code=202)
async def send_single_draft_route(
    draft_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Accept immediately; Gmail send runs in a worker thread (no long HTTP hold / client timeout race)."""
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    try:
        validate_outbound_draft_sendable(db, draft)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    background_tasks.add_task(_queue_send_one_draft, draft_id)
    return {"draft_id": draft_id, "status": "queued"}


@router.post("/runs/{run_id}/send", status_code=202)
async def send_run_drafts_route(
    run_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is closed — cannot send new outreach")
    drafts = list_sendable_email_drafts_by_run(db, run_id)
    if not drafts:
        raise HTTPException(status_code=400, detail="No approved sendable drafts for this run")
    background_tasks.add_task(_queue_send_run, run_id)
    return {"run_id": run_id, "status": "queued", "draft_count": len(drafts)}


@router.get("/runs/{run_id}/summary")
def run_summary_route(run_id: int, db: Session = Depends(get_db)):
    if not get_run(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return get_run_summary(db, run_id)
