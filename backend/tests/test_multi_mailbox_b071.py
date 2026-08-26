"""B-071 stage B (multi-mailbox Gmail creds) — env-registry resolution, mailbox threading through
send_one_draft / send_one_reply_draft, and OAuth state carrying mailbox_email.

HARD INVARIANT under test throughout: when no GMAIL_ACCOUNT__<SLUG> entry exists for a mailbox
(including mailbox_email=None), every resolver falls back byte-for-byte to today's globals
(GOOGLE_REFRESH_TOKEN / GMAIL_SEND_AS_EMAIL) — Alexey's mailbox behavior is unchanged.

gmail_oauth tests never let reload_google_env() touch the real backend/.env (it holds live Google
OAuth credentials) — the _isolate_env autouse fixture stubs reload_google_env/peek_env_key_from_files
and clears any GOOGLE_*/GMAIL_* vars so each test controls os.environ directly (same "offline"
philosophy as conftest.py / test_email_verification.py).
"""

from __future__ import annotations

import json
import os

import pytest

from app.services import gmail_oauth as go

# ---------------------------------------------------------------------------------------------
# Isolation from the real backend/.env (has a live GOOGLE_REFRESH_TOKEN)
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_gmail_env(monkeypatch):
    monkeypatch.setattr(go, "reload_google_env", lambda: None)
    monkeypatch.setattr(go, "peek_env_key_from_files", lambda key: "")
    for k in list(os.environ):
        if k.startswith("GOOGLE_") or k.startswith("GMAIL_"):
            monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------------------------
# B5.1 — _mailbox_creds / google_refresh_token_value resolution
# ---------------------------------------------------------------------------------------------


def test_slug_for_mailbox_normalizes_punctuation():
    assert go._slug_for_mailbox("stepan@alexstaff.agency") == "STEPAN_ALEXSTAFF_AGENCY"
    assert go._slug_for_mailbox("a.b-c@d.com") == "A_B_C_D_COM"


def test_mailbox_creds_none_falls_back_to_global(monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    monkeypatch.setenv("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency")
    creds = go._mailbox_creds(None)
    assert creds == {"refresh_token": "global-token", "send_as": "alex@alexstaff.agency", "found": False}


def test_mailbox_creds_unconfigured_mailbox_falls_back_to_global(monkeypatch):
    """Invariant: a mailbox_email with no registry entry behaves exactly like mailbox_email=None."""
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    monkeypatch.setenv("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency")
    with_mailbox = go._mailbox_creds("stepan@alexstaff.agency")
    without_mailbox = go._mailbox_creds(None)
    assert with_mailbox == without_mailbox == {
        "refresh_token": "global-token", "send_as": "alex@alexstaff.agency", "found": False,
    }


def test_mailbox_creds_found_uses_per_mailbox_entry(monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    monkeypatch.setenv("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency")
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"send_as": "stepan@alexstaff.agency", "refresh_token": "stepan-token"}),
    )
    creds = go._mailbox_creds("stepan@alexstaff.agency")
    assert creds == {"refresh_token": "stepan-token", "send_as": "stepan@alexstaff.agency", "found": True}
    # Global mailbox (Alexey) is untouched by the presence of Stepan's entry.
    assert go._mailbox_creds(None)["refresh_token"] == "global-token"


def test_mailbox_creds_malformed_json_falls_back_to_global(monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    monkeypatch.setenv("GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY", "not-json")
    creds = go._mailbox_creds("stepan@alexstaff.agency")
    assert creds["found"] is False
    assert creds["refresh_token"] == "global-token"


def test_mailbox_creds_missing_refresh_token_falls_back_to_global(monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"send_as": "stepan@alexstaff.agency"}),
    )
    creds = go._mailbox_creds("stepan@alexstaff.agency")
    assert creds["found"] is False
    assert creds["refresh_token"] == "global-token"


def test_mailbox_creds_missing_send_as_defaults_to_mailbox_email(monkeypatch):
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"refresh_token": "stepan-token"}),
    )
    creds = go._mailbox_creds("stepan@alexstaff.agency")
    assert creds == {"refresh_token": "stepan-token", "send_as": "stepan@alexstaff.agency", "found": True}


def test_google_refresh_token_value_wraps_mailbox_creds(monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "global-token")
    assert go.google_refresh_token_value() == "global-token"
    assert go.google_refresh_token_value("nobody@example.com") == "global-token"
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"send_as": "stepan@alexstaff.agency", "refresh_token": "stepan-token"}),
    )
    assert go.google_refresh_token_value("stepan@alexstaff.agency") == "stepan-token"
    assert go.google_refresh_token_value() == "global-token"  # default mailbox unaffected


# ---------------------------------------------------------------------------------------------
# B5.2 — resolve_outbound_from_mime picks the per-mailbox send_as when found
# ---------------------------------------------------------------------------------------------


def test_resolve_outbound_from_mime_uses_per_mailbox_send_as(monkeypatch):
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"send_as": "stepan@alexstaff.agency", "refresh_token": "tok"}),
    )
    monkeypatch.setattr(
        go,
        "list_send_as_rows",
        lambda access_token: [
            {"sendAsEmail": "stepan@alexstaff.agency", "verificationStatus": "accepted", "displayName": "Stepan"},
        ],
    )
    hdr, addr = go.resolve_outbound_from_mime("access-tok", "stepan@alexstaff.agency")
    assert addr == "stepan@alexstaff.agency"
    assert "Stepan" in hdr


def test_resolve_outbound_from_mime_no_mailbox_email_keeps_global_default(monkeypatch):
    """No GMAIL_SEND_AS_EMAIL, no mailbox_email -> falls through to the account's own profile
    email, exactly as before B-071 stage B."""
    monkeypatch.setattr(go, "gmail_profile_email", lambda access_token: "alex@alexstaff.agency")
    hdr, addr = go.resolve_outbound_from_mime("access-tok")
    assert addr == "alex@alexstaff.agency"
    assert hdr == "alex@alexstaff.agency"


# ---------------------------------------------------------------------------------------------
# B5.3 — persist / clear round-trip through the actual env-file writer
# ---------------------------------------------------------------------------------------------


@pytest.fixture()
def _writable_env(tmp_path, monkeypatch):
    """Point the env writer at a throwaway file and force write-permission, without touching the
    real backend/.env."""
    import app.services.env_bootstrap as envb

    tmp_env = tmp_path / "test.env"
    tmp_env.write_text("")
    monkeypatch.setattr(envb, "ENV_FILE_PATH", tmp_env)
    monkeypatch.setattr(envb, "ordered_env_candidates", lambda: [tmp_env])
    monkeypatch.setattr(go, "bootstrap_env_write_allowed", lambda: True)
    monkeypatch.setattr(go, "env_write_blocked_reason", lambda: "")
    # persist/clear call reload_google_env() themselves via _mailbox_creds; let it actually load
    # from tmp_env this time (real load_env_from_file, patched ordered_env_candidates above).
    monkeypatch.setattr(go, "reload_google_env", lambda: envb.load_env_from_file())
    return tmp_env


def test_persist_and_read_back_per_mailbox_refresh_token(_writable_env):
    go.persist_google_refresh_token("new-stepan-token", "stepan@alexstaff.agency")
    creds = go._mailbox_creds("stepan@alexstaff.agency")
    assert creds == {
        "refresh_token": "new-stepan-token", "send_as": "stepan@alexstaff.agency", "found": True,
    }


def test_clear_google_refresh_token_if_allowed_clears_only_that_mailbox(_writable_env):
    go.persist_google_refresh_token("tok-a", "stepan@alexstaff.agency")
    os.environ["GOOGLE_REFRESH_TOKEN"] = "alexey-global-token"
    assert go._mailbox_creds("stepan@alexstaff.agency")["found"] is True

    go.clear_google_refresh_token_if_allowed("stepan@alexstaff.agency")

    # dotenv's override=True only overrides keys still present in the file — it never deletes a
    # process-env key just because the file line was removed, so re-assert against the file (what
    # clear_google_refresh_token_if_allowed actually promises) rather than the in-process cache a
    # fresh interpreter would never have populated in the first place.
    file_text = _writable_env.read_text()
    assert "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY" not in file_text
    # Clearing Stepan's entry must not touch Alexey's global token.
    assert go._mailbox_creds(None)["refresh_token"] == "alexey-global-token"


# ---------------------------------------------------------------------------------------------
# B5.4 — OAuth state carries mailbox_email and still verifies
# ---------------------------------------------------------------------------------------------


def test_oauth_state_round_trips_mailbox_email():
    state = go.sign_oauth_state(
        {
            "return_path": "/",
            "public_origin": "http://localhost:5173",
            "redirect_uri": "http://localhost:5173/api/oauth/google/callback",
            "mailbox_email": "stepan@alexstaff.agency",
        },
    )
    data = go.verify_oauth_state(state)
    assert data["mailbox_email"] == "stepan@alexstaff.agency"


def test_oauth_state_without_mailbox_email_defaults_to_missing():
    """Old-style state (pre B-071 stage B, or the default single-mailbox connect) has no
    mailbox_email key at all — callback code must read it with .get() and treat it as None."""
    state = go.sign_oauth_state(
        {
            "return_path": "/",
            "public_origin": "http://localhost:5173",
            "redirect_uri": "http://localhost:5173/api/oauth/google/callback",
        },
    )
    data = go.verify_oauth_state(state)
    assert data.get("mailbox_email") is None


# ---------------------------------------------------------------------------------------------
# B5.5 — mailbox threading through send_one_draft / send_one_reply_draft (DB-backed)
# ---------------------------------------------------------------------------------------------


def _make_run(db, suffix: str):
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup

    project = Project(name=f"multi-mailbox-test-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name=f"multi-mailbox-run-{suffix}")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, sender_signature_html="<p>Alexey</p>"))
    db.commit()
    return run


def test_send_one_draft_uses_send_queue_mailbox(db, monkeypatch):
    import app.services.email_provider as ep
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.send_queue import SendQueueItem
    from app.services.email_sender import send_one_draft

    run = _make_run(db, "queue-mailbox")
    contact = Contact(run_id=run.id, name="X", email=f"mb1-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    db.add(
        SendQueueItem(
            draft_id=draft.id, run_id=run.id, contact_id=contact.id,
            mailbox_email="stepan@alexstaff.agency", touch_number=1, not_before=None,
        ),
    )
    db.commit()

    captured = {}

    def fake_send_html(*, to_email, subject, body_html, mailbox_email=None):
        captured["mailbox_email"] = mailbox_email
        return {"provider_message_id": "m1", "thread_id": "t1", "provider": "gmail"}

    monkeypatch.setattr(ep, "google_client_configured", lambda: True)
    monkeypatch.setattr(ep, "google_refresh_token_value", lambda mailbox_email=None: "tok")
    monkeypatch.setattr(ep, "send_html_via_gmail", fake_send_html)

    result = send_one_draft(db, draft.id)

    assert result["status"] == "sent"
    assert captured["mailbox_email"] == "stepan@alexstaff.agency"


def test_send_one_draft_falls_back_to_persona_mailbox_when_not_queued(db, monkeypatch):
    """No send_queue row (e.g. a manual send before enqueue) -> resolve via the run's persona."""
    import app.services.email_provider as ep
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.persona import Persona
    from app.services.email_sender import send_one_draft

    run = _make_run(db, "persona-mailbox")
    persona = Persona(
        slug=f"stepan-test-{run.id}", display_name="Stepan", primary_mailbox_email="stepan@alexstaff.agency",
    )
    db.add(persona)
    db.commit()
    run.persona_id = persona.id
    db.add(run)
    db.commit()

    contact = Contact(run_id=run.id, name="X", email=f"mb2-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()
    # Deliberately no SendQueueItem for this draft.

    captured = {}

    def fake_send_html(*, to_email, subject, body_html, mailbox_email=None):
        captured["mailbox_email"] = mailbox_email
        return {"provider_message_id": "m2", "thread_id": "t2", "provider": "gmail"}

    monkeypatch.setattr(ep, "google_client_configured", lambda: True)
    monkeypatch.setattr(ep, "google_refresh_token_value", lambda mailbox_email=None: "tok")
    monkeypatch.setattr(ep, "send_html_via_gmail", fake_send_html)

    result = send_one_draft(db, draft.id)

    assert result["status"] == "sent"
    assert captured["mailbox_email"] == "stepan@alexstaff.agency"


def test_send_one_draft_no_queue_no_persona_falls_back_to_alexey_mailbox(db, monkeypatch):
    """Invariant: a run with no persona_id and no queued mailbox still resolves to Alexey's own
    mailbox (persona_service's "alexey" default) — matches today's single-tenant behavior."""
    import app.services.email_provider as ep
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.services.email_sender import send_one_draft

    run = _make_run(db, "default-mailbox")
    contact = Contact(run_id=run.id, name="X", email=f"mb3-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", review_status="approved",
    )
    db.add(draft)
    db.commit()

    captured = {}

    def fake_send_html(*, to_email, subject, body_html, mailbox_email=None):
        captured["mailbox_email"] = mailbox_email
        return {"provider_message_id": "m3", "thread_id": "t3", "provider": "gmail"}

    monkeypatch.setattr(ep, "google_client_configured", lambda: True)
    monkeypatch.setattr(ep, "google_refresh_token_value", lambda mailbox_email=None: "tok")
    monkeypatch.setattr(ep, "send_html_via_gmail", fake_send_html)

    result = send_one_draft(db, draft.id)

    assert result["status"] == "sent"
    assert captured["mailbox_email"] == "alex@alexstaff.agency"


def test_send_one_reply_draft_uses_original_send_queue_mailbox(db, monkeypatch):
    """A reply must go out from the same mailbox as the original outbound send."""
    import app.services.email_provider as ep
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.email_thread import EmailThread
    from app.models.send_queue import STATE_SENT, SendQueueItem
    from app.repositories.reply_draft_repo import create_reply_draft
    from app.services.reply_sender import send_one_reply_draft

    run = _make_run(db, "reply-mailbox")
    contact = Contact(run_id=run.id, name="X", email=f"reply1-{run.id}@example.com", company="Acme")
    db.add(contact)
    db.commit()
    orig_draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="sent", review_status="approved",
    )
    db.add(orig_draft)
    db.commit()
    db.add(
        SendQueueItem(
            draft_id=orig_draft.id, run_id=run.id, contact_id=contact.id,
            mailbox_email="stepan@alexstaff.agency", touch_number=1, not_before=None,
            state=STATE_SENT,
        ),
    )
    thread = EmailThread(
        run_id=run.id, contact_id=contact.id, draft_id=orig_draft.id, subject="Hi", status="open",
    )
    db.add(thread)
    db.commit()

    reply = create_reply_draft(
        db, run_id=run.id, thread_id=thread.id, contact_id=contact.id,
        reply_type="manual", to_email=contact.email, subject="Re: Hi", body="Reply body",
        status="draft", review_status="approved",
    )

    captured = {}

    def fake_send_html(*, to_email, subject, body_html, mailbox_email=None):
        captured["mailbox_email"] = mailbox_email
        return {"provider_message_id": "m4", "thread_id": "t4", "provider": "gmail"}

    monkeypatch.setattr(ep, "google_client_configured", lambda: True)
    monkeypatch.setattr(ep, "google_refresh_token_value", lambda mailbox_email=None: "tok")
    monkeypatch.setattr(ep, "send_html_via_gmail", fake_send_html)

    result = send_one_reply_draft(db, reply.id)

    assert result["status"] == "sent"
    assert captured["mailbox_email"] == "stepan@alexstaff.agency"
