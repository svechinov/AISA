"""DB-backed tests for send-queue fixes (backlog B-013 §4 enqueue-on-edit, §7 atomic claim,
§9 company-normalization gate; B-026 reschedule-reason). Requires the ai_biz_os_realrun.db
snapshot (see conftest.py)."""

from datetime import datetime, timedelta

import sqlalchemy as sa

from app.db import SessionLocal
from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.project import Project
from app.models.run import Run
from app.models.run_setup import RunSetup
from app.models.send_queue import STATE_QUEUED, STATE_RELEASING, SendQueueItem
from app.repositories.email_draft_repo import update_email_draft_fields
from app.repositories.send_queue_repo import (
    claim_item,
    get_by_draft,
    list_rescheduled_today,
    reschedule_item,
)
from app.services.send_queue_service import enqueue_draft
from app.services.sending_gates import _company_has_active_touch


def _make_run(db, suffix: str):
    project = Project(name=f"send-queue-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"send-queue-run-{suffix}")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, sender_signature_html="<p>Alexey</p>"))
    db.commit()
    return run


def test_editing_a_pending_draft_enqueues_it(db):
    """B-013 §4: PATCH /email-drafts/{id}/edit sets review_status='edited' (sendable), but
    previously never reached send_queue — the worker would never pick it up."""
    run = _make_run(db, "edit-enqueue")
    contact = Contact(run_id=run.id, name="X", email=f"edit-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Original", body="Body", status="draft", review_status="pending",
    )
    db.add(draft)
    db.commit()

    assert get_by_draft(db, draft.id) is None  # not queued while pending

    updated = update_email_draft_fields(db, draft, subject="Edited")
    assert updated.review_status == "edited"
    enqueue_draft(db, updated)

    item = get_by_draft(db, draft.id)
    assert item is not None
    assert item.state == STATE_QUEUED


def test_editing_twice_does_not_duplicate_the_queue_item(db):
    run = _make_run(db, "edit-idempotent")
    contact = Contact(run_id=run.id, name="X", email=f"edit2-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Original", body="Body", status="draft", review_status="pending",
    )
    db.add(draft)
    db.commit()

    update_email_draft_fields(db, draft, subject="Edit 1")
    enqueue_draft(db, draft)
    update_email_draft_fields(db, draft, subject="Edit 2")
    enqueue_draft(db, draft)

    count = db.execute(
        sa.text("SELECT COUNT(*) FROM send_queue WHERE draft_id = :d"), {"d": draft.id},
    ).scalar()
    assert count == 1


def test_claim_item_is_atomic_under_concurrent_ticks(db):
    """B-013 §7: two overlapping scheduler ticks (background loop + manual /queue/tick) must not
    both be able to release the same due item — that was the double-send race."""
    run = _make_run(db, "claim")
    contact = Contact(run_id=run.id, name="X", email=f"claim-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    enqueue_draft(db, draft)
    item = get_by_draft(db, draft.id)
    item.state = STATE_QUEUED
    item.not_before = datetime.utcnow() - timedelta(minutes=1)
    db.add(item)
    db.commit()
    item_id = item.id

    # Two independent sessions, simulating two ticks racing for the same item.
    db_a = SessionLocal()
    db_b = SessionLocal()
    try:
        claim_a = claim_item(db_a, item_id)
        claim_b = claim_item(db_b, item_id)
        assert claim_a is True
        assert claim_b is False
    finally:
        db_a.close()
        db_b.close()

    final = db.query(SendQueueItem).filter_by(id=item_id).first()
    db.refresh(final)
    assert final.state == STATE_RELEASING
    assert final.attempts == 1


def test_claim_item_fails_on_already_claimed_item(db):
    run = _make_run(db, "claim-twice")
    contact = Contact(run_id=run.id, name="X", email=f"claim2-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    enqueue_draft(db, draft)
    item = get_by_draft(db, draft.id)
    item.state = STATE_QUEUED
    db.add(item)
    db.commit()

    assert claim_item(db, item.id) is True
    assert claim_item(db, item.id) is False  # already RELEASING, not QUEUED anymore


def test_company_gate_ignores_case_and_padding(db):
    """B-013 §9: EmailDraft.company is free text (Apollo/OSINT/import), so 'Acme Games' and
    'acme games ' must be recognized as the same company by the one-dialog-per-company gate."""
    run = _make_run(db, "company-norm")
    contact = Contact(run_id=run.id, name="X", email=f"company-{run.id}@example.com", company="Acme Games")
    db.add(contact)
    db.commit()
    sent = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme Games", to_email=contact.email,
        subject="Hi", body="Body", status="sent", tracking_status="sent",
        sent_at=datetime.utcnow(),
    )
    db.add(sent)
    db.commit()

    cutoff = datetime.utcnow() - timedelta(days=4)
    assert _company_has_active_touch(db, "Acme Games", None, cutoff) is True
    assert _company_has_active_touch(db, "acme games", None, cutoff) is True
    assert _company_has_active_touch(db, "  ACME GAMES  ", None, cutoff) is True
    assert _company_has_active_touch(db, "A Totally Different Co", None, cutoff) is False


def test_reschedule_item_stores_last_reschedule_reason(db):
    """B-026: the VOKI/Burny incident — a transient gate failure's reason vanished (Send queue
    'Reason' column was blank for queued items), so a correct auto-reschedule looked like an
    unexplained stuck item. reschedule_item() must now persist GateResult.reason and clear any
    stale hold_reason."""
    run = _make_run(db, "reschedule-reason")
    contact = Contact(run_id=run.id, name="X", email=f"reschedule-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    enqueue_draft(db, draft)
    item = get_by_draft(db, draft.id)
    item.hold_reason = "stale hold from a previous tick"
    db.add(item)
    db.commit()

    new_slot = datetime.utcnow() + timedelta(days=1)
    updated = reschedule_item(db, item, new_slot, reason="company already has an active dialog")

    assert updated.state == STATE_QUEUED
    assert updated.hold_reason is None
    assert updated.last_reschedule_reason == "company already has an active dialog"
    assert updated.not_before == new_slot


def test_reschedule_item_without_reason_clears_stale_one(db):
    """The reason param is optional — a call without it (none currently exists, but the
    signature allows it) must not crash and must not leave a stale reason from an earlier push."""
    run = _make_run(db, "reschedule-no-reason")
    contact = Contact(run_id=run.id, name="X", email=f"reschedule2-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    enqueue_draft(db, draft)
    item = get_by_draft(db, draft.id)
    item.last_reschedule_reason = "outside send window"
    db.add(item)
    db.commit()

    updated = reschedule_item(db, item, datetime.utcnow() + timedelta(days=1))

    assert updated.last_reschedule_reason is None


def test_list_rescheduled_today_filters_by_window_and_reason(db):
    """Feeds the daily digest note (B-026 part а: 'запланировано на сегодня, но не ушло') —
    only queued items with a reason set inside the given UTC window should be picked up."""
    run = _make_run(db, "reschedule-window")
    contact = Contact(run_id=run.id, name="X", email=f"reschedule3-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    enqueue_draft(db, draft)
    item = get_by_draft(db, draft.id)

    now = datetime.utcnow()
    reschedule_item(db, item, now + timedelta(days=1), reason="outside send window")

    found_ids = [i.id for i in list_rescheduled_today(db, now - timedelta(hours=1), now + timedelta(hours=1))]
    assert item.id in found_ids

    # Outside the window -> not picked up.
    missed_ids = [
        i.id for i in list_rescheduled_today(db, now + timedelta(hours=2), now + timedelta(hours=3))
    ]
    assert item.id not in missed_ids
