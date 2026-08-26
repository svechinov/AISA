"""B-138: two gaps found on re-verification of the B-139 real-sync wiring.

1) Quote-stripping trap: our own CAN-SPAM opt-out signature ("...reply "STOP" and I'll take you
   off my list.") is echoed back inside the quoted history on almost every reply. Classifying the
   raw body would read our own canned "STOP" as the contact's opt-out — ANY reply, including a
   positive one, would be misclassified as unsubscribe and the contact permanently banned.
   reply_classifier.strip_quoted_reply() must cut the quote before classify_reply() looks at it.

2) Suppression cooldown (decision 20.07): unsubscribe stays a permanent do-not-contact, but
   not_interested is only a 6-month cooldown — a studio's open roles look different by then.
   suppression_list.expires_at (NULL = forever) plus suppression_repo.is_suppressed() ignoring
   expired rows is the single mechanism; nothing else should duplicate this gating.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.contact import Contact
from app.models.project import Project
from app.models.run import Run
from app.repositories.email_thread_repo import create_email_thread
from app.repositories.suppression_repo import add_suppression, get_suppression, is_suppressed
from app.services.follow_up_service import (
    NOT_INTERESTED_SUPPRESSION_COOLDOWN_DAYS,
    create_next_action_for_thread,
)
from app.services.reply_classifier import classify_reply, strip_quoted_reply

# ---------------------------------------------------------------------------------------------
# Quote-stripping trap: our own "reply STOP" signature quoted back must not read as unsubscribe.
# ---------------------------------------------------------------------------------------------

_QUOTED_STEPAN_SIGNATURE = (
    "Stepan Pakhanov\n"
    "COO, AlexStaff Agency — recruiting for game studios and publishers since 2006\n"
    "stepan@alexstaff.agency · alexstaff.agency\n"
    "Based in the US\n"
    "\n"
    "123 Main St, Austin, TX 78701\n"
    "If you'd rather not hear from us, just reply \"STOP\" and I'll take you off my list."
)


def test_classify_reply_on_wrote_quote_with_our_stop_signature_is_interested():
    """The mandatory B-138 regression: a realistic reply with the original (STOP-bearing) message
    quoted below an "On ... wrote:" line must classify on the NEW text only."""
    body = (
        "Sounds good, let's set up a call.\n"
        "\n"
        "On Mon, Jul 20, 2026 at 10:03 AM Stepan Pakhanov <stepan@alexstaff.agency> wrote:\n"
        "> Hi John,\n"
        ">\n"
        "> ... (our original outreach email) ...\n"
        ">\n"
        f"> {_QUOTED_STEPAN_SIGNATURE.replace(chr(10), chr(10) + '> ')}"
    )
    result = classify_reply(body)
    assert result is not None
    assert result["label"] == "interested"


def test_classify_reply_gt_prefixed_quote_with_our_stop_signature_is_interested():
    body = (
        "sounds good, let's talk more\n"
        "> Stepan Pakhanov\n"
        "> If you'd rather not hear from us, just reply \"STOP\" and I'll take you off my list.\n"
    )
    result = classify_reply(body)
    assert result is not None
    assert result["label"] == "interested"


def test_classify_reply_top_posted_signature_without_quote_marker_is_interested():
    """Backstop: some clients top-post without any ">" or "On ... wrote:" line at all — the
    signature-fingerprint scan must still find and cut our own canned opt-out text."""
    body = "Sounds good, let's set up a call.\n\n" + _QUOTED_STEPAN_SIGNATURE
    result = classify_reply(body)
    assert result is not None
    assert result["label"] == "interested"


def test_classify_reply_returns_none_when_nothing_left_after_stripping():
    """A reply that's 100% quoted history (e.g. an empty reply-all) must not be guessed at."""
    body = "On Mon, Jul 20, 2026 at 10:03 AM Stepan Pakhanov <stepan@alexstaff.agency> wrote:\n> Hi John,\n> body text"
    assert classify_reply(body) is None


def test_strip_quoted_reply_cuts_at_original_message_marker():
    body = "No thanks.\n-----Original Message-----\nFrom: stepan@alexstaff.agency\nSTOP"
    assert strip_quoted_reply(body) == "No thanks."


# ---------------------------------------------------------------------------------------------
# Suppression cooldown: unsubscribe permanent, not_interested 6-month, expiry gates is_suppressed.
# ---------------------------------------------------------------------------------------------


def _make_thread(db, *, classification: str, suffix: str):
    project = Project(name=f"b138-cooldown-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"b138-cooldown-run-{suffix}")
    db.add(run)
    db.commit()
    contact = Contact(run_id=run.id, name="X", email=f"b138-cooldown-{suffix}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")
    thread.classification = classification
    db.add(thread)
    db.commit()
    return thread, contact


def test_unsubscribe_suppression_has_no_expiry(db):
    thread, contact = _make_thread(db, classification="unsubscribe", suffix="unsub")
    create_next_action_for_thread(db, thread.id)
    entry = get_suppression(db, contact.email)
    assert entry is not None
    assert entry.expires_at is None


def test_not_interested_suppression_expires_in_about_six_months(db):
    before = datetime.utcnow()
    thread, contact = _make_thread(db, classification="not_interested", suffix="notint")
    create_next_action_for_thread(db, thread.id)
    after = datetime.utcnow()

    entry = get_suppression(db, contact.email)
    assert entry is not None
    assert entry.expires_at is not None
    expected_low = before + timedelta(days=NOT_INTERESTED_SUPPRESSION_COOLDOWN_DAYS - 1)
    expected_high = after + timedelta(days=NOT_INTERESTED_SUPPRESSION_COOLDOWN_DAYS + 1)
    assert expected_low <= entry.expires_at <= expected_high


def test_is_suppressed_ignores_expired_entry(db):
    email = "b138-expired@example.com"
    add_suppression(
        db, email, reason="not_interested", expires_at=datetime.utcnow() - timedelta(days=1),
    )
    assert is_suppressed(db, email) is False


def test_is_suppressed_true_for_not_yet_expired_entry(db):
    email = "b138-active-cooldown@example.com"
    add_suppression(
        db, email, reason="not_interested", expires_at=datetime.utcnow() + timedelta(days=30),
    )
    assert is_suppressed(db, email) is True


def test_is_suppressed_true_for_permanent_entry(db):
    email = "b138-permanent@example.com"
    add_suppression(db, email, reason="unsubscribe")
    assert is_suppressed(db, email) is True
