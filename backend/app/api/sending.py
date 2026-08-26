import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.repositories.email_draft_repo import get_email_draft, list_sendable_email_drafts_by_run
from app.repositories.run_repo import get_run
from app.repositories.send_queue_repo import (
    cancel_item,
    get_item,
    is_paused,
    list_items,
    requeue_held,
    set_paused,
)
from app.repositories.sending_policy_repo import get_policy_by_id, list_sending_policies
from app.models.send_queue import STATE_QUEUED
from app.schemas.run import TotalPerformanceRead
from app.schemas.sending_policy import SendingPolicyUpdate
from app.services.sending_gates import parse_hhmm
from app.services.email_sender import (
    send_approved_drafts_for_run_in_thread,
    send_one_draft_in_thread,
    validate_outbound_draft_sendable,
)
from app.services.run_display_service import get_total_performance_global
from app.services.run_summary_service import get_run_summary
from app.services.sending_scheduler import run_queue_tick

router = APIRouter(prefix="/sending", tags=["sending"])
_log = logging.getLogger(__name__)


def _queue_item_to_dict(item) -> dict:
    return {
        "id": item.id,
        "draft_id": item.draft_id,
        "run_id": item.run_id,
        "contact_id": item.contact_id,
        "mailbox_email": item.mailbox_email,
        "touch_number": item.touch_number,
        "not_before": item.not_before.isoformat() if item.not_before else None,
        "state": item.state,
        "hold_reason": item.hold_reason,
        "last_reschedule_reason": item.last_reschedule_reason,
        "attempts": item.attempts,
    }


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


# --------------------------------------------------------------------------- send queue

@router.get("/queue")
def list_queue_route(
    state: str | None = Query(default=None, description="Filter by state (queued|held|releasing|sent|canceled)."),
    db: Session = Depends(get_db),
):
    states = (state,) if state else None
    items = list_items(db, states=states)
    return {"paused": is_paused(db), "items": [_queue_item_to_dict(i) for i in items]}


@router.get("/schedule")
def queue_schedule_route(db: Session = Depends(get_db)):
    """Upcoming plan: queued items with an assigned slot, earliest first (the live send schedule)."""
    items = list_items(db, states=(STATE_QUEUED,))
    upcoming = [i for i in items if i.not_before is not None]
    return {"paused": is_paused(db), "items": [_queue_item_to_dict(i) for i in upcoming]}


@router.post("/queue/pause")
def queue_pause_route(db: Session = Depends(get_db)):
    set_paused(db, True)
    return {"paused": True}


@router.post("/queue/resume")
def queue_resume_route(db: Session = Depends(get_db)):
    set_paused(db, False)
    return {"paused": False}


@router.post("/queue/tick")
def queue_tick_route(db: Session = Depends(get_db)):
    """Force one worker tick now (ops/testing). Respects pause and all gates."""
    return run_queue_tick(db)


@router.post("/queue/{item_id}/hold")
def queue_hold_route(item_id: int, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    from app.repositories.send_queue_repo import set_state
    from app.models.send_queue import STATE_HELD

    set_state(db, item, STATE_HELD, hold_reason="held manually")
    return _queue_item_to_dict(item)


@router.post("/queue/{item_id}/release")
def queue_release_route(item_id: int, db: Session = Depends(get_db)):
    """Return a held item to the queue for the next tick (re-checks gates then)."""
    item = get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    requeue_held(db, item)
    return _queue_item_to_dict(item)


@router.post("/queue/{item_id}/cancel")
def queue_cancel_route(item_id: int, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    cancel_item(db, item)
    return _queue_item_to_dict(item)


# --------------------------------------------------------------------------- sending policies

def _policy_to_dict(p) -> dict:
    return {
        "id": p.id,
        "mailbox_email": p.mailbox_email,
        "daily_cap": p.daily_cap,
        "hourly_cap": p.hourly_cap,
        "min_gap_minutes": p.min_gap_minutes,
        "gap_jitter_minutes": p.gap_jitter_minutes,
        "send_days_first_touch": p.send_days_first_touch,
        "send_days_follow_up": p.send_days_follow_up,
        "window_start": p.window_start,
        "window_end": p.window_end,
        "timezone": p.timezone,
        "warmup_ramp_json": p.warmup_ramp_json,
        "follow_up_after_business_days": p.follow_up_after_business_days,
        "max_touches": p.max_touches,
        "enabled": p.enabled,
    }


@router.get("/policies")
def list_sending_policies_route(db: Session = Depends(get_db)):
    return {"items": [_policy_to_dict(p) for p in list_sending_policies(db)]}


@router.patch("/policies/{policy_id}")
def update_sending_policy_route(
    policy_id: int,
    payload: SendingPolicyUpdate,
    db: Session = Depends(get_db),
):
    policy = get_policy_by_id(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Sending policy not found")

    updates = payload.model_dump(exclude_unset=True)

    # Cross-field window check against the MERGED row — catches a partial update (only one of
    # start/end sent) that would invert the window relative to the unchanged side. Both sides are
    # always valid HH:MM by construction (schema-validated or already-stored), so parsing can't fail.
    merged_start = parse_hhmm(updates.get("window_start", policy.window_start), None)
    merged_end = parse_hhmm(updates.get("window_end", policy.window_end), None)
    if merged_start >= merged_end:
        raise HTTPException(status_code=400, detail="window_start must be before window_end")

    for field, value in updates.items():
        setattr(policy, field, value)
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return _policy_to_dict(policy)
