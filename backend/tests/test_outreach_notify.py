"""Offline tests for the outreach Telegram-notify layer (backlog B-021 step 3).

notify() must never raise or block the caller, and the tracking-service hooks must fire it
exactly on the success paths (not on skipped/no-op returns).
"""

from __future__ import annotations

import threading

import pytest

from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.models.project import Project
from app.models.run import Run
from app.services import outreach_notify
from app.services import email_tracking_service as ets


def _make_run(db, suffix: str) -> Run:
    project = Project(name=f"outreach-notify-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"notify-run-{suffix}")
    db.add(run)
    db.commit()
    return run


def _make_draft(db, run: Run, suffix: str, **kwargs) -> EmailDraft:
    contact = Contact(run_id=run.id, name="X", email=f"notify-{suffix}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    fields = dict(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="sent", tracking_status="sent",
    )
    fields.update(kwargs)  # callers may override defaults (e.g. tracking_status)
    draft = EmailDraft(**fields)
    db.add(draft)
    db.commit()
    return draft


# --------------------------------------------------------------------------- notify()

def test_notify_never_raises_even_if_send_fails(monkeypatch):
    threads: list[threading.Thread] = []
    real_thread_cls = threading.Thread

    def _tracking_thread(*args, **kwargs):
        t = real_thread_cls(*args, **kwargs)
        threads.append(t)
        return t

    monkeypatch.setattr(outreach_notify.threading, "Thread", _tracking_thread)
    monkeypatch.setattr(
        outreach_notify.telegram_notify, "send",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    outreach_notify.notify("test message")  # must not raise

    assert len(threads) == 1
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()


def test_notify_calls_telegram_notify_send_with_project_and_timeout(monkeypatch):
    captured = {}

    def _fake_send(project, text, **kwargs):
        captured["project"] = project
        captured["text"] = text
        captured["kwargs"] = kwargs
        return True

    monkeypatch.setattr(outreach_notify.telegram_notify, "send", _fake_send)

    outreach_notify.notify("hello")

    # Runs in a daemon thread — give it a moment to execute.
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=5)

    assert captured["project"] == "AI-Biz-OS"
    assert captured["text"] == "hello"
    assert captured["kwargs"]["timeout"] == 5.0


# --------------------------------------------------------------------------- email_tracking_service hooks

def test_register_replied_event_calls_notify(db, monkeypatch):
    calls = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "replied")
    draft = _make_draft(db, run, "replied")

    out = ets.register_replied_event(db, draft.id)

    assert out["skipped"] is False
    assert len(calls) == 1
    assert "📩" in calls[0]
    assert str(run.id) in calls[0]


def test_register_replied_event_skips_notify_when_already_replied(db, monkeypatch):
    calls = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "replied-skip")
    draft = _make_draft(db, run, "replied-skip", tracking_status="replied")

    out = ets.register_replied_event(db, draft.id)

    assert out["skipped"] is True
    assert calls == []


def test_register_bounced_event_calls_notify_with_reason(db, monkeypatch):
    calls = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "bounced")
    draft = _make_draft(db, run, "bounced")

    out = ets.register_bounced_event(db, draft.id, error_message="mailbox full")

    assert out["skipped"] is False
    assert len(calls) == 1
    assert "↩️" in calls[0]
    assert "mailbox full" in calls[0]


def test_register_bounced_event_skips_notify_when_already_bounced(db, monkeypatch):
    calls = []
    monkeypatch.setattr(ets, "notify", lambda text: calls.append(text))

    run = _make_run(db, "bounced-skip")
    draft = _make_draft(db, run, "bounced-skip", tracking_status="bounced")

    out = ets.register_bounced_event(db, draft.id)

    assert out["skipped"] is True
    assert calls == []


# --------------------------------------------------------------------------- smoke imports

def test_orchestrator_and_sending_scheduler_import_cleanly():
    import app.services.orchestrator  # noqa: F401
    import app.services.sending_scheduler  # noqa: F401
