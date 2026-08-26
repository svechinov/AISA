"""B-139: reply classification wired end-to-end.

Before this: thread.classification was only ever written by the dev/mock endpoint
(inbox_service.receive_mock_reply) — the real Gmail sync (gmail_tracking_sync_service) marked a
draft "replied" but never classified the reply, so suppression/follow-up-tasks never fired for a
real reply. This file covers: the shared apply_reply_classification() code path (all classes,
including suppression on not_interested/unsubscribe), the mock endpoint's historical behavior
staying unchanged (create_task=False), the real sync now calling it on inbound import, DSN/bounce
messages being skipped, and the classification riding along in the Telegram notify text.
"""

from __future__ import annotations

import base64
from datetime import datetime

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.project import Project
from app.models.run import Run
from app.repositories.email_thread_repo import create_email_thread
from app.repositories.follow_up_task_repo import list_follow_up_tasks_by_thread
from app.repositories.suppression_repo import get_suppression
from app.services import email_tracking_service as ets
from app.services import gmail_tracking_sync_service as gts
from app.services import inbound_delivery_llm_service as idls
from app.services.inbox_service import apply_reply_classification, receive_mock_reply


def _make_run(db, suffix: str) -> Run:
    project = Project(name=f"b139-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"b139-run-{suffix}")
    db.add(run)
    db.commit()
    return run


def _make_contact(db, run: Run, suffix: str) -> Contact:
    contact = Contact(run_id=run.id, name="X", email=f"b139-{suffix}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    return contact


def _make_sent_draft(db, run: Run, contact: Contact, suffix: str, **overrides) -> EmailDraft:
    fields = dict(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="sent", tracking_status="sent",
    )
    fields.update(overrides)
    draft = EmailDraft(**fields)
    db.add(draft)
    db.commit()
    return draft


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _gmail_message(*, mid: str, tid: str, internal_ms: int, from_addr: str, to_addr: str, subject: str, body_text: str) -> dict:
    return {
        "id": mid,
        "threadId": tid,
        "internalDate": str(internal_ms),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
            ],
            "body": {"data": _b64(body_text)},
        },
    }


# ------------------------------------------------------------------- apply_reply_classification()

def test_apply_reply_classification_interested_creates_task_no_suppression(db):
    run = _make_run(db, "interested")
    contact = _make_contact(db, run, "interested")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    out = apply_reply_classification(db, thread, "I'm interested, tell me more", create_task=True)

    assert out["classification"] == "interested"
    assert out["next_action"]["task_type"] == "reply_to_interested"
    tasks = list_follow_up_tasks_by_thread(db, thread.id)
    assert any(t.task_type == "reply_to_interested" for t in tasks)
    assert get_suppression(db, contact.email) is None


def test_apply_reply_classification_not_interested_adds_suppression(db):
    run = _make_run(db, "notint")
    contact = _make_contact(db, run, "notint")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    out = apply_reply_classification(db, thread, "No thanks, not interested", create_task=True)

    assert out["classification"] == "not_interested"
    entry = get_suppression(db, contact.email)
    assert entry is not None
    assert entry.reason == "not_interested"
    tasks = list_follow_up_tasks_by_thread(db, thread.id)
    assert any(t.task_type == "close_thread" for t in tasks)


def test_apply_reply_classification_unsubscribe_adds_suppression(db):
    run = _make_run(db, "unsub")
    contact = _make_contact(db, run, "unsub")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    out = apply_reply_classification(db, thread, "please unsubscribe me", create_task=True)

    assert out["classification"] == "unsubscribe"
    assert get_suppression(db, contact.email) is not None


def test_apply_reply_classification_unclear_does_not_raise_and_creates_no_task(db):
    """follow_up_service.create_next_action_for_thread has no recipe for "unclear" — must not crash."""
    run = _make_run(db, "unclear")
    contact = _make_contact(db, run, "unclear")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    out = apply_reply_classification(db, thread, "asdkjhasdkjh random text zzz", create_task=True)

    assert out["classification"] == "unclear"
    assert out["next_action"] is None
    assert list_follow_up_tasks_by_thread(db, thread.id) == []


def test_apply_reply_classification_create_task_false_skips_follow_up(db):
    run = _make_run(db, "notask")
    contact = _make_contact(db, run, "notask")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    out = apply_reply_classification(db, thread, "No thanks, not interested", create_task=False)

    assert out["classification"] == "not_interested"
    assert out["next_action"] is None
    assert list_follow_up_tasks_by_thread(db, thread.id) == []
    assert get_suppression(db, contact.email) is None


def test_apply_reply_classification_none_from_classifier_keeps_prior_classification(db):
    """classify_reply() returns None when the body is entirely quoted history (B-138 quote-
    stripping) — apply_reply_classification must not crash and must not overwrite the thread's
    existing classification with nothing."""
    run = _make_run(db, "noneclass")
    contact = _make_contact(db, run, "noneclass")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    apply_reply_classification(db, thread, "I'm interested, tell me more", create_task=True)
    assert thread.classification == "interested"

    fully_quoted_body = "> reply \"STOP\" and I'll take you off my list."
    out = apply_reply_classification(db, thread, fully_quoted_body, create_task=True)

    assert out["classification"] == "interested"  # unchanged
    assert out["next_action"] is None
    assert thread.classification == "interested"


def test_apply_reply_classification_reclassifies_on_second_call(db):
    """Dialogue moves on — a later inbound message overwrites the class, no manual override exists."""
    run = _make_run(db, "reclass")
    contact = _make_contact(db, run, "reclass")
    thread = create_email_thread(db, run.id, contact.id, None, subject="Hi")

    apply_reply_classification(db, thread, "not now, maybe later", create_task=True)
    assert thread.classification == "ask_later"

    apply_reply_classification(db, thread, "ok, I'm interested, tell me more", create_task=True)
    assert thread.classification == "interested"


# ------------------------------------------------------------------- mock endpoint unchanged

def test_receive_mock_reply_still_does_not_create_follow_up_task_or_suppression(db):
    """B-139: mock endpoint's behavior is explicitly preserved (create_task=False), not changed
    silently as a side effect of routing it through the shared apply_reply_classification()."""
    run = _make_run(db, "mock")
    contact = _make_contact(db, run, "mock")
    draft = _make_sent_draft(db, run, contact, "mock")
    thread = create_email_thread(db, run.id, contact.id, draft.id, subject="Hi")

    out = receive_mock_reply(
        db, draft.id, from_email=contact.email, to_email="alex@alexstaff.agency",
        subject="Re: Hi", body="No thanks, not interested",
    )

    assert out["classification"] == "not_interested"
    assert list_follow_up_tasks_by_thread(db, thread.id) == []
    assert get_suppression(db, contact.email) is None


# ------------------------------------------------------------------- real Gmail sync wiring

def test_sync_thread_messages_classifies_inbound_reply_and_wires_suppression(db, monkeypatch):
    run = _make_run(db, "sync")
    contact = _make_contact(db, run, "sync")
    draft = _make_sent_draft(db, run, contact, "sync", sent_at=datetime(2026, 1, 1, 9, 0, 0))
    thread = create_email_thread(
        db, run.id, contact.id, draft.id, subject="Hi", provider_thread_id="gth-sync-1",
    )

    inbound_ms = int(datetime(2026, 1, 2, 9, 0, 0).timestamp() * 1000)
    fake_thread = {
        "messages": [
            _gmail_message(
                mid="gmsg-sync-1", tid="gth-sync-1", internal_ms=inbound_ms,
                from_addr=contact.email, to_addr="alex@alexstaff.agency",
                subject="Re: Hi", body_text="No thanks, not interested",
            ),
        ],
    }

    monkeypatch.setattr(gts, "require_gmail_configured", lambda: None)
    monkeypatch.setattr(gts, "_our_address_set", lambda token: {"alex@alexstaff.agency"})
    monkeypatch.setattr(gts, "gmail_get_thread_full", lambda token, tid: fake_thread)
    # Offline test: this reply's body doesn't hit the DSN heuristic gate, so the LLM delivery pass
    # already no-ops on its own heuristic — but stub llm_configured too, belt-and-braces (local
    # .env has a real ANTHROPIC_API_KEY; no test in this file should ever place a live LLM call).
    monkeypatch.setattr(idls, "llm_configured", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    out = gts.sync_thread_messages_for_run(db, run.id, access_token="faketoken")

    assert out["imported"] == 1
    assert out["replied_marked"] == 1
    db.refresh(thread)
    assert thread.classification == "not_interested"
    entry = get_suppression(db, contact.email)
    assert entry is not None
    assert entry.reason == "not_interested"
    tasks = list_follow_up_tasks_by_thread(db, thread.id)
    assert any(t.task_type == "close_thread" for t in tasks)
    assert calls, "register_replied_event must have notified"
    assert "класс: not_interested" in calls[0]


def test_sync_thread_messages_skips_classification_for_dsn_bounce(db, monkeypatch):
    """A mailer-daemon DSN must not get run through the reply classifier — it isn't a human reply."""
    run = _make_run(db, "dsn")
    contact = _make_contact(db, run, "dsn")
    draft = _make_sent_draft(db, run, contact, "dsn", sent_at=datetime(2026, 1, 1, 9, 0, 0))
    thread = create_email_thread(
        db, run.id, contact.id, draft.id, subject="Hi", provider_thread_id="gth-dsn-1",
    )

    inbound_ms = int(datetime(2026, 1, 2, 9, 0, 0).timestamp() * 1000)
    fake_thread = {
        "messages": [
            _gmail_message(
                mid="gmsg-dsn-1", tid="gth-dsn-1", internal_ms=inbound_ms,
                from_addr="mailer-daemon@googlemail.com", to_addr="alex@alexstaff.agency",
                subject="Delivery Status Notification (Failure)",
                body_text="550 5.1.1 The email account that you tried to reach does not exist.",
            ),
        ],
    }

    monkeypatch.setattr(gts, "require_gmail_configured", lambda: None)
    monkeypatch.setattr(gts, "_our_address_set", lambda token: {"alex@alexstaff.agency"})
    monkeypatch.setattr(gts, "gmail_get_thread_full", lambda token, tid: fake_thread)
    monkeypatch.setattr(idls, "llm_configured", lambda: False)  # offline test — no live LLM call

    out = gts.sync_thread_messages_for_run(db, run.id, access_token="faketoken")

    assert out["imported"] == 1
    db.refresh(thread)
    assert thread.classification is None
    assert get_suppression(db, contact.email) is None
    assert list_follow_up_tasks_by_thread(db, thread.id) == []


# ------------------------------------------------------------------- register_replied_event(classification=)

def test_register_replied_event_includes_classification_in_notify(db, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "notifyclass")
    contact = _make_contact(db, run, "notifyclass")
    draft = _make_sent_draft(db, run, contact, "notifyclass")

    out = ets.register_replied_event(db, draft.id, classification="interested")

    assert out["skipped"] is False
    assert "класс: interested" in calls[0]


def test_register_replied_event_without_classification_omits_suffix(db, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "noclass")
    contact = _make_contact(db, run, "noclass")
    draft = _make_sent_draft(db, run, contact, "noclass")

    out = ets.register_replied_event(db, draft.id)

    assert out["skipped"] is False
    assert "класс" not in calls[0]
