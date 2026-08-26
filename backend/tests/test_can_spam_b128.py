"""B-128 Phase 1: CAN-SPAM mechanics — reply-based opt-out routed to suppression, and the
send gate that blocks a US-track (Stepan) persona while CAN_SPAM_POSTAL_ADDRESS is unset without
touching Alexey's live Cyprus send. DB-backed (requires ai_biz_os_realrun.db snapshot, same as
test_contactability.py — skips otherwise).
"""

from app.config import settings
from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.email_thread import EmailThread
from app.models.persona import Persona
from app.models.project import Project
from app.models.run import Run
from app.models.run_setup import RunSetup
from app.models.sending_policy import SendingPolicy
from app.models.suppression_entry import REASON_UNSUBSCRIBE
from app.repositories.sending_policy_repo import get_default_policy
from app.repositories.suppression_repo import get_suppression
from app.services.contactability import is_contactable
from app.services.email_sender import validate_outbound_draft_sendable
from app.services.follow_up_service import create_next_action_for_thread
from app.services.persona_service import (
    CAN_SPAM_ADDRESS_PLACEHOLDER,
    default_alexey_persona,
    STEPAN_SIGNATURE_HTML,
    stepan_persona_kwargs,
)
from app.services.outreach_email_pipeline import _no_vacancy_block
from app.services.reply_classifier import classify_reply
from app.services.send_queue_service import enqueue_draft


# ---------------------------------------------------------------------------------------------
# reply_classifier: opt-out keywords route to "unsubscribe", ahead of not_interested
# ---------------------------------------------------------------------------------------------


def test_classify_reply_stop_is_unsubscribe():
    assert classify_reply("Please STOP emailing me.")["label"] == "unsubscribe"


def test_classify_reply_unsubscribe_word_is_unsubscribe():
    assert classify_reply("unsubscribe me from this list")["label"] == "unsubscribe"


def test_classify_reply_remove_me_is_unsubscribe():
    assert classify_reply("remove me please")["label"] == "unsubscribe"


def test_classify_reply_stop_substring_does_not_false_positive():
    """B-128 concern: word-boundary matching — "stop" inside another word must not trigger."""
    result = classify_reply("We had nonstop growth this year, sounds good, let's talk")
    assert result["label"] != "unsubscribe"


def test_classify_reply_no_thanks_still_not_interested():
    """Regression on branch order: unsubscribe check must not swallow a plain decline."""
    assert classify_reply("No thanks, we're all set") == {
        "label": "not_interested",
        "confidence": "high",
        "reason": "negative intent keywords",
    }


# ---------------------------------------------------------------------------------------------
# follow_up_service: unsubscribe classification -> suppression with REASON_UNSUBSCRIBE
# ---------------------------------------------------------------------------------------------


def _make_thread(db, *, classification: str, suffix: str):
    project = Project(name=f"can-spam-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"can-spam-run-{suffix}")
    db.add(run)
    db.commit()
    contact = Contact(run_id=run.id, name="X", email=f"{suffix}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    thread = EmailThread(
        run_id=run.id, contact_id=contact.id, subject="Hi", classification=classification,
    )
    db.add(thread)
    db.commit()
    return thread, contact


def test_unsubscribe_classification_adds_suppression_with_reason(db):
    thread, contact = _make_thread(db, classification="unsubscribe", suffix="unsub")
    create_next_action_for_thread(db, thread.id)
    entry = get_suppression(db, contact.email)
    assert entry is not None
    assert entry.reason == REASON_UNSUBSCRIBE


def test_unsubscribe_suppression_stops_contactability(db):
    """contactability.py centrally gates send + follow-up for anyone in suppression (B-128 1b)."""
    thread, contact = _make_thread(db, classification="unsubscribe", suffix="unsub-gate")
    create_next_action_for_thread(db, thread.id)
    result = is_contactable(db, contact.email, contact)
    assert result.ok is False
    assert "suppression" in result.reason


# ---------------------------------------------------------------------------------------------
# sending_gates / email_sender: CAN-SPAM postal-address gate — Stepan blocked, Alexey untouched
# ---------------------------------------------------------------------------------------------


def _make_run_with_persona(db, *, persona: Persona | None, signature_html: str, suffix: str):
    project = Project(name=f"can-spam-gate-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(
        project_id=project.id, workflow_name="outreach", name=f"can-spam-gate-run-{suffix}",
        persona_id=persona.id if persona else None,
    )
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, sender_signature_html=signature_html))
    db.commit()
    return run


def _make_stepan_persona(db, *, suffix: str) -> Persona:
    """Own unique slug per test — the process-wide DB copy is shared across tests, and slug is unique."""
    kwargs = {**stepan_persona_kwargs(), "slug": f"stepan-test-{suffix}"}
    persona = Persona(**kwargs)
    db.add(persona)
    db.commit()
    return persona


def _make_draft(db, run, *, suffix: str):
    contact = Contact(run_id=run.id, name="X", email=f"{suffix}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    return draft


def test_stepan_signature_has_address_placeholder_and_optout():
    assert CAN_SPAM_ADDRESS_PLACEHOLDER in STEPAN_SIGNATURE_HTML
    assert "STOP" in STEPAN_SIGNATURE_HTML


def test_gate_blocks_stepan_send_when_address_empty(db, monkeypatch):
    monkeypatch.setattr(settings, "CAN_SPAM_POSTAL_ADDRESS", "")
    stepan = _make_stepan_persona(db, suffix="noaddr")
    run = _make_run_with_persona(
        db, persona=stepan, signature_html=STEPAN_SIGNATURE_HTML, suffix="stepan-noaddr",
    )
    draft = _make_draft(db, run, suffix="stepan-noaddr")
    try:
        validate_outbound_draft_sendable(db, draft)
        assert False, "expected ValueError while CAN_SPAM_POSTAL_ADDRESS is empty"
    except ValueError as e:
        assert "CAN-SPAM" in str(e)


def test_gate_allows_stepan_send_once_address_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "CAN_SPAM_POSTAL_ADDRESS", "123 Main St, Austin, TX 78701")
    stepan = _make_stepan_persona(db, suffix="addr")
    run = _make_run_with_persona(
        db, persona=stepan, signature_html=STEPAN_SIGNATURE_HTML, suffix="stepan-addr",
    )
    draft = _make_draft(db, run, suffix="stepan-addr")
    validate_outbound_draft_sendable(db, draft)  # must not raise


def test_gate_does_not_block_alexey_send_when_address_empty(db, monkeypatch):
    """B-128 1c main regression: the CAN-SPAM address gate must not affect Alexey's live Cyprus
    send, whose signature template has no address placeholder at all."""
    monkeypatch.setattr(settings, "CAN_SPAM_POSTAL_ADDRESS", "")
    run = _make_run_with_persona(
        db, persona=None, signature_html="<p>Alexey</p>", suffix="alexey-noaddr",
    )
    draft = _make_draft(db, run, suffix="alexey-noaddr")
    validate_outbound_draft_sendable(db, draft)  # must not raise


# ---------------------------------------------------------------------------------------------
# send_queue_service: an explicit-persona run must be queued on that persona's mailbox
# ---------------------------------------------------------------------------------------------


def _make_policy(db, mailbox_email: str) -> SendingPolicy:
    policy = SendingPolicy(mailbox_email=mailbox_email, warmup_ramp_json={})
    db.add(policy)
    db.commit()
    return policy


def test_enqueue_routes_persona_run_to_persona_mailbox(db):
    """B-128 blocker: enqueue_draft used to fall through to the default (Alexey) policy for every
    draft, so a Stepan-signed US draft would have been sent from alex@ — the queue item's mailbox
    wins over the run persona in email_sender._resolve_send_mailbox."""
    mailbox = "stepan-route@alexstaff.agency"
    _make_policy(db, mailbox)
    kwargs = {**stepan_persona_kwargs(), "slug": "stepan-test-route", "primary_mailbox_email": mailbox}
    persona = Persona(**kwargs)
    db.add(persona)
    db.commit()

    run = _make_run_with_persona(
        db, persona=persona, signature_html=STEPAN_SIGNATURE_HTML, suffix="stepan-route",
    )
    item = enqueue_draft(db, _make_draft(db, run, suffix="stepan-route"))
    assert item is not None
    assert item.mailbox_email == mailbox


def test_enqueue_refuses_persona_without_policy(db):
    """No policy for the persona's mailbox = do not queue. Falling back to the default policy would
    silently send another sender's mail from Alexey's mailbox."""
    kwargs = {
        **stepan_persona_kwargs(),
        "slug": "stepan-test-nopolicy",
        "primary_mailbox_email": "stepan-nopolicy@alexstaff.agency",
    }
    persona = Persona(**kwargs)
    db.add(persona)
    db.commit()

    run = _make_run_with_persona(
        db, persona=persona, signature_html=STEPAN_SIGNATURE_HTML, suffix="stepan-nopolicy",
    )
    assert enqueue_draft(db, _make_draft(db, run, suffix="stepan-nopolicy")) is None


def test_enqueue_persona_less_run_still_uses_default_policy(db):
    """Regression: Alexey's live runs carry no persona_id — they must keep using the default policy."""
    default = get_default_policy(db)
    assert default is not None, "fixture DB must carry at least one enabled sending policy"

    run = _make_run_with_persona(
        db, persona=None, signature_html="<p>Alexey</p>", suffix="alexey-route",
    )
    item = enqueue_draft(db, _make_draft(db, run, suffix="alexey-route"))
    assert item is not None
    assert item.mailbox_email == default.mailbox_email


# ---------------------------------------------------------------------------------------------
# outreach_email_pipeline: the "One co-founder to another" opener is about the SENDER too
# ---------------------------------------------------------------------------------------------


def test_no_vacancy_founder_opener_only_for_a_founder_sender():
    """B-128: the opener asserts the sender is a co-founder. Stepan is the COO, and his finale says
    so — using it on his run put a flat contradiction inside one email (caught on draft 84, run 4)."""
    alexey = default_alexey_persona()
    stepan = Persona(**{**stepan_persona_kwargs(), "slug": "stepan-test-opener"})

    assert "One co-founder to another" in _no_vacancy_block("English", "Founder", alexey)
    assert "One co-founder to another" not in _no_vacancy_block("English", "Founder", stepan)
    # A non-founder recipient never gets the peer opener, whoever sends.
    assert "One co-founder to another" not in _no_vacancy_block("English", "CEO", alexey)
    # No persona threaded through (legacy callers) keeps the old recipient-only behavior.
    assert "One co-founder to another" in _no_vacancy_block("English", "Founder")


def test_no_vacancy_ru_founder_opener_follows_the_same_sender_rule():
    stepan = Persona(**{**stepan_persona_kwargs(), "slug": "stepan-test-opener-ru"})
    assert "кофаундер кофаундеру" in _no_vacancy_block("Russian", "Founder", default_alexey_persona())
    assert "кофаундер кофаундеру" not in _no_vacancy_block("Russian", "Founder", stepan)
