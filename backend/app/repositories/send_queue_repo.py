from __future__ import annotations

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.send_queue import (
    ACTIVE_STATES,
    STATE_CANCELED,
    STATE_HELD,
    STATE_QUEUED,
    STATE_RELEASING,
    STATE_SENT,
    SendQueueItem,
)
from app.models.system_setting import SystemSetting

_PAUSE_KEY = "send_queue_paused"


def get_by_draft(db: Session, draft_id: int) -> SendQueueItem | None:
    return db.query(SendQueueItem).filter(SendQueueItem.draft_id == draft_id).first()


def get_item(db: Session, item_id: int) -> SendQueueItem | None:
    return db.query(SendQueueItem).filter(SendQueueItem.id == item_id).first()


def create_item(
    db: Session,
    *,
    draft_id: int,
    run_id: int,
    contact_id: int | None,
    mailbox_email: str,
    touch_number: int,
    not_before: datetime | None,
) -> SendQueueItem:
    item = SendQueueItem(
        draft_id=draft_id,
        run_id=run_id,
        contact_id=contact_id,
        mailbox_email=mailbox_email,
        touch_number=touch_number,
        not_before=not_before,
        state=STATE_QUEUED,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def mark_draft_queue_item_sent(db: Session, draft_id: int) -> None:
    """Sync an active queue item to 'sent' after its draft was sent (manual send or worker).

    Idempotent: keeps the queue consistent with a manual POST /sending/drafts/{id}/send that
    bypasses the worker, so no stale 'queued' item lingers for an already-sent draft.
    """
    item = (
        db.query(SendQueueItem)
        .filter(SendQueueItem.draft_id == draft_id, SendQueueItem.state.in_(ACTIVE_STATES))
        .first()
    )
    if item is None:
        return
    item.state = STATE_SENT
    item.hold_reason = None
    db.add(item)
    db.commit()


def latest_planned_not_before(db: Session, mailbox_email: str) -> datetime | None:
    """Tail of the currently-planned queue for a mailbox — the planner spaces new items after it."""
    row = (
        db.query(SendQueueItem.not_before)
        .filter(
            SendQueueItem.mailbox_email == mailbox_email,
            SendQueueItem.state.in_(ACTIVE_STATES),
            SendQueueItem.not_before.isnot(None),
        )
        .order_by(SendQueueItem.not_before.desc())
        .first()
    )
    return row[0] if row and row[0] else None


def reset_stale_releasing(db: Session, cutoff_utc: datetime) -> int:
    """Park items stuck in 'releasing' (a crash between mark-releasing and send) as held.

    Returns how many were reset. Guards against orphaned in-flight items after a worker restart.
    """
    stale = (
        db.query(SendQueueItem)
        .filter(
            SendQueueItem.state == STATE_RELEASING,
            SendQueueItem.updated_at < cutoff_utc,
        )
        .all()
    )
    for item in stale:
        item.state = STATE_HELD
        item.hold_reason = "stale releasing (worker restart?) — release to retry"
        db.add(item)
    if stale:
        db.commit()
    return len(stale)


def due_items(db: Session, now_utc: datetime, limit: int = 50) -> list[SendQueueItem]:
    """Queued items whose slot has arrived, oldest slot first."""
    return (
        db.query(SendQueueItem)
        .filter(
            SendQueueItem.state == STATE_QUEUED,
            SendQueueItem.not_before.isnot(None),
            SendQueueItem.not_before <= now_utc,
        )
        .order_by(SendQueueItem.not_before.asc())
        .limit(limit)
        .all()
    )


def count_active_items_for_run(db: Session, run_id: int) -> int:
    """How many not-yet-sent items (queued/held/releasing) remain for this run's queue."""
    return (
        db.query(SendQueueItem)
        .filter(SendQueueItem.run_id == run_id, SendQueueItem.state.in_(ACTIVE_STATES))
        .count()
    )


def count_sent_items_for_run(db: Session, run_id: int) -> int:
    """How many of this run's queued items have already shipped (state=sent)."""
    return (
        db.query(SendQueueItem)
        .filter(SendQueueItem.run_id == run_id, SendQueueItem.state == STATE_SENT)
        .count()
    )


def list_rescheduled_today(db: Session, since_utc: datetime, until_utc: datetime) -> list[SendQueueItem]:
    """Items transient-rescheduled inside [since_utc, until_utc) — a reschedule only fires once an
    item's slot is due, so this is exactly "was due today but pushed to a later slot" (B-026).
    Feeds the daily digest note about sends that looked short vs. what was planned.
    """
    return (
        db.query(SendQueueItem)
        .filter(
            SendQueueItem.state == STATE_QUEUED,
            SendQueueItem.last_reschedule_reason.isnot(None),
            SendQueueItem.updated_at >= since_utc,
            SendQueueItem.updated_at < until_utc,
        )
        .order_by(SendQueueItem.updated_at.asc())
        .all()
    )


def list_items(db: Session, states: tuple[str, ...] | None = None, limit: int = 200) -> list[SendQueueItem]:
    q = db.query(SendQueueItem)
    if states:
        q = q.filter(SendQueueItem.state.in_(states))
    return q.order_by(SendQueueItem.not_before.is_(None), SendQueueItem.not_before.asc()).limit(limit).all()


def claim_item(db: Session, item_id: int) -> bool:
    """Atomically transition a QUEUED item to RELEASING. Returns False if it was no longer
    'queued' (another tick already claimed it) — the caller must skip the item rather than send it.

    Replaces a read-then-write (fetch the ORM object, then `set_state`) with a conditional
    UPDATE ... WHERE state='queued': the manual `POST /sending/queue/tick` endpoint runs in a
    threadpool thread and can overlap the background worker's own thread, so two ticks could
    previously both pass gates for the same due item and both call send_one_draft — a double send
    (backlog B-013 §7). SQLite serializes writers, so only one of two concurrent UPDATEs with this
    WHERE clause can affect a row; the loser's rowcount is 0.
    """
    result = db.execute(
        update(SendQueueItem)
        .where(SendQueueItem.id == item_id, SendQueueItem.state == STATE_QUEUED)
        .values(state=STATE_RELEASING, attempts=SendQueueItem.attempts + 1)
    )
    db.commit()
    return result.rowcount > 0


def set_state(
    db: Session,
    item: SendQueueItem,
    state: str,
    *,
    hold_reason: str | None = None,
    bump_attempts: bool = False,
) -> SendQueueItem:
    item.state = state
    item.hold_reason = hold_reason
    if bump_attempts:
        item.attempts = (item.attempts or 0) + 1
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def reschedule_item(
    db: Session, item: SendQueueItem, not_before: datetime, reason: str | None = None,
) -> SendQueueItem:
    """Push a transiently-blocked item to a new slot; keep it queued (never park it held).

    ``reason`` is the gate's GateResult.reason (why it was pushed) — stored so the Send queue UI
    can show it instead of leaving the item's "Reason" column blank (B-026).
    """
    item.state = STATE_QUEUED
    item.hold_reason = None
    item.last_reschedule_reason = reason
    item.not_before = not_before
    item.attempts = (item.attempts or 0) + 1
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def requeue_held(db: Session, item: SendQueueItem, not_before: datetime | None = None) -> SendQueueItem:
    item.state = STATE_QUEUED
    item.hold_reason = None
    if not_before is not None:
        item.not_before = not_before
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def cancel_item(db: Session, item: SendQueueItem) -> SendQueueItem:
    return set_state(db, item, STATE_CANCELED)


def revive_canceled_item(
    db: Session,
    item: SendQueueItem,
    *,
    not_before: datetime,
    touch_number: int,
) -> SendQueueItem:
    """Bring a canceled item back to queued with a fresh slot/touch (re-approve after cancel).

    Reuses the row so the UNIQUE(draft_id) constraint is never violated by a second insert.
    """
    item.state = STATE_QUEUED
    item.hold_reason = None
    item.not_before = not_before
    item.touch_number = touch_number
    item.attempts = 0
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# --------------------------------------------------------------------------- global pause (kill switch)

def is_paused(db: Session) -> bool:
    row = db.query(SystemSetting).filter(SystemSetting.key == _PAUSE_KEY).first()
    return bool(row and (row.value or "").strip() == "1")


def set_paused(db: Session, paused: bool) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == _PAUSE_KEY).first()
    if row is None:
        row = SystemSetting(key=_PAUSE_KEY, value="1" if paused else "0")
        db.add(row)
    else:
        row.value = "1" if paused else "0"
        db.add(row)
    db.commit()
