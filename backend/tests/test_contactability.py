"""DB-backed tests for the shared is_contactable predicate (backlog B-013 §1/§2/§5) and the
manual-send chokepoint that now uses it. Requires the ai_biz_os_realrun.db snapshot (see
conftest.py) — skips otherwise, same as the rest of this DB-backed suite."""

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.project import Project
from app.models.run import Run
from app.models.run_setup import RunSetup
from app.repositories.suppression_repo import add_suppression
from app.services.contactability import is_contactable
from app.services.email_sender import validate_outbound_draft_sendable


def _make_run(db, *, signed: bool, suffix: str):
    project = Project(name=f"contactability-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"contactability-run-{suffix}")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, sender_signature_html="<p>Alexey</p>" if signed else None))
    db.commit()
    return run


def test_is_contactable_normal_contact_passes(db):
    run = _make_run(db, signed=True, suffix="ok")
    contact = Contact(run_id=run.id, name="Ok", email=f"ok-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    result = is_contactable(db, contact.email, contact)
    assert result.ok is True


def test_is_contactable_dead_verification_blocks(db):
    run = _make_run(db, signed=True, suffix="dead")
    contact = Contact(
        run_id=run.id, name="Dead", email=f"dead-{run.id}@example.com", company="Acme",
        email_verification_status="dead",
    )
    db.add(contact)
    db.commit()
    result = is_contactable(db, contact.email, contact)
    assert result.ok is False
    assert "dead" in result.reason


def test_is_contactable_dead_mailbox_health_blocks(db):
    run = _make_run(db, signed=True, suffix="deadmbx")
    contact = Contact(
        run_id=run.id, name="DeadMbx", email=f"deadmbx-{run.id}@example.com", company="Acme",
        email_health="dead_mailbox",
    )
    db.add(contact)
    db.commit()
    result = is_contactable(db, contact.email, contact)
    assert result.ok is False
    assert "dead_mailbox" in result.reason


def test_is_contactable_catch_all_does_not_block(db):
    """B-013 §2 decision: catch-all is common on real corporate domains and must not withhold a lead."""
    run = _make_run(db, signed=True, suffix="catchall")
    contact = Contact(
        run_id=run.id, name="CatchAll", email=f"catchall-{run.id}@example.com", company="Acme",
        email_verification_status="catch_all",
    )
    db.add(contact)
    db.commit()
    result = is_contactable(db, contact.email, contact)
    assert result.ok is True


def test_is_contactable_unknown_does_not_block(db):
    run = _make_run(db, signed=True, suffix="unknown")
    contact = Contact(
        run_id=run.id, name="Unknown", email=f"unknown-{run.id}@example.com", company="Acme",
        email_verification_status="unknown",
    )
    db.add(contact)
    db.commit()
    assert is_contactable(db, contact.email, contact).ok is True


def test_is_contactable_suppressed_blocks(db):
    run = _make_run(db, signed=True, suffix="suppressed")
    email = f"suppressed-{run.id}@example.com"
    contact = Contact(run_id=run.id, name="Suppressed", email=email, company="Acme")
    db.add(contact)
    db.commit()
    add_suppression(db, email, reason="manual", note="test")
    result = is_contactable(db, email, contact)
    assert result.ok is False
    assert "suppression" in result.reason


def test_manual_send_chokepoint_blocks_suppressed_recipient(db):
    """B-013 §1: the manual POST /sending/drafts/{id}/send path used to skip this entirely."""
    run = _make_run(db, signed=True, suffix="manual-suppressed")
    email = f"manual-suppressed-{run.id}@example.com"
    contact = Contact(run_id=run.id, name="X", email=email, company="Acme")
    db.add(contact)
    db.commit()
    add_suppression(db, email, reason="manual", note="test")
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    try:
        validate_outbound_draft_sendable(db, draft)
        assert False, "expected ValueError for a suppressed recipient"
    except ValueError as e:
        assert "suppression" in str(e)


def test_manual_send_chokepoint_requires_signature(db):
    """B-013 §6: a run without a configured signature must not be able to send at all."""
    run = _make_run(db, signed=False, suffix="nosig")
    contact = Contact(run_id=run.id, name="X", email=f"nosig-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    try:
        validate_outbound_draft_sendable(db, draft)
        assert False, "expected ValueError for a signature-less run"
    except ValueError as e:
        assert "signature" in str(e)


def test_manual_send_chokepoint_passes_for_clean_signed_contact(db):
    run = _make_run(db, signed=True, suffix="clean")
    contact = Contact(run_id=run.id, name="Clean", email=f"clean-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    validate_outbound_draft_sendable(db, draft)  # must not raise
