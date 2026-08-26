"""B-547: ops-dashboard policy resolution — a persona run must show ITS mailbox's policy, not the
default one, and a persona without a sending_policy must surface as "none" rather than silently
borrowing the default. Requires ai_biz_os_realrun.db snapshot (see conftest.py)."""

from __future__ import annotations

from app.api.ops import ops_summary_route
from app.models.persona import Persona
from app.models.project import Project
from app.models.run import Run
from app.models.sending_policy import SendingPolicy


def _make_project_and_run(db, suffix: str, *, persona_id: int | None = None) -> Run:
    project = Project(name=f"ops-summary-b547-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(
        project_id=project.id,
        workflow_name="outreach",
        name=f"ops-summary-run-{suffix}",
        persona_id=persona_id,
    )
    db.add(run)
    db.commit()
    return run


def test_run_with_persona_policy_uses_persona_mailbox(db):
    suffix = "run-persona"
    mailbox = f"persona-b547-{suffix}@example.com"
    persona = Persona(
        slug=f"persona-b547-{suffix}", display_name="Test Persona B547", primary_mailbox_email=mailbox,
    )
    db.add(persona)
    db.commit()
    db.add(SendingPolicy(mailbox_email=mailbox))
    db.commit()
    run = _make_project_and_run(db, suffix, persona_id=persona.id)

    data = ops_summary_route(run_id=run.id, db=db)

    assert data["today"]["policy_source"] == "run_persona"
    assert data["today"]["policy_configured"] is True
    assert data["today"]["mailbox_email"] == mailbox
    assert data["today"]["persona_slug"] == persona.slug
    assert data["today"]["persona_name"] == "Test Persona B547"
    assert data["today"]["run_id"] == run.id


def test_run_without_persona_id_uses_default_policy(db):
    """Грабля проекта: run.persona_id=NULL молча резолвится в персону alexey — на витрине это
    ДОЛЖНО остаться source="default", не "run_persona", иначе она соврёт уверенно."""
    suffix = "no-persona"
    run = _make_project_and_run(db, suffix, persona_id=None)

    data = ops_summary_route(run_id=run.id, db=db)

    assert data["today"]["policy_source"] == "default"
    assert data["today"]["persona_slug"] is None
    assert data["today"]["run_id"] == run.id


def test_persona_without_policy_is_none_and_not_configured(db):
    suffix = "no-policy"
    mailbox = f"persona-b547-{suffix}@example.com"
    persona = Persona(
        slug=f"persona-b547-{suffix}", display_name="No Policy Persona", primary_mailbox_email=mailbox,
    )
    db.add(persona)
    db.commit()
    run = _make_project_and_run(db, suffix, persona_id=persona.id)

    data = ops_summary_route(run_id=run.id, db=db)

    assert data["today"]["policy_source"] == "none"
    assert data["today"]["policy_configured"] is False
    assert data["today"]["persona_slug"] == persona.slug


def test_no_run_id_keeps_previous_default_behavior(db):
    """No run_id at all (dashboard's default state before a run is picked) -> same as before B-547."""
    data = ops_summary_route(run_id=None, db=db)

    assert data["today"]["policy_source"] == "default"
    assert data["today"]["run_id"] is None


def test_next_slots_only_from_run_mailbox_not_other_mailboxes(db):
    """Code review afe4e2d находка 2: next_slots собирал queued-элементы ВСЕХ ящиков, а не только
    ящика политики этого рана — чужой ящик с будущим слотом не должен всплыть здесь."""
    from datetime import datetime, timedelta

    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.send_queue import SendQueueItem

    suffix = "next-slots-mailbox"
    mailbox = f"persona-b547-{suffix}@example.com"
    other_mailbox = f"other-b547-{suffix}@example.com"
    persona = Persona(
        slug=f"persona-b547-{suffix}", display_name="Next Slots Persona", primary_mailbox_email=mailbox,
    )
    db.add(persona)
    db.commit()
    db.add(SendingPolicy(mailbox_email=mailbox))
    db.commit()
    run = _make_project_and_run(db, suffix, persona_id=persona.id)

    contact = Contact(run_id=run.id, name="Y", email=f"c-{run.id}@example.com", company="Acme")
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
            mailbox_email=other_mailbox, touch_number=1,
            not_before=datetime.utcnow() + timedelta(minutes=5),
        ),
    )
    db.commit()

    data = ops_summary_route(run_id=run.id, db=db)

    assert data["today"]["mailbox_email"] == mailbox
    assert data["today"]["next_slots"] == []
