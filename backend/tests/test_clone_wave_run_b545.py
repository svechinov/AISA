"""B-545: clone-wave (POST /runs/{run_id}/clone-wave, repo clone_wave_run) — заводить ран новой
волны штатным путём вместо прямого INSERT (прецедент 17-18.08, ран 6 «Волна 2 — партия 1» завели
INSERT'ом со status='active' у соседнего рана и без рабочей кнопки продолжения).
Requires ai_biz_os_realrun.db snapshot (see conftest.py)."""

from __future__ import annotations

import pytest

from app.models.persona import Persona
from app.models.project import Project
from app.models.run import Run
from app.models.run_setup import RunSetup
from app.repositories.run_repo import clone_wave_run
from app.repositories.step_repo import list_steps_by_run


def _make_source_run(db, suffix: str, *, persona_id: int | None = None) -> Run:
    project = Project(name=f"clone-wave-b545-{suffix}", type="generic")
    db.add(project)
    db.commit()
    run = Run(
        project_id=project.id,
        workflow_name="generic_outreach",
        name=f"clone-wave-source-{suffix}",
        notes="source notes",
        segment="Cyprus",
        persona_id=persona_id,
    )
    db.add(run)
    db.commit()
    db.add(
        RunSetup(
            run_id=run.id,
            prompt_setup_text="Offer: source offer",
            critic_canon_text="source canon",
            osint_prompt="source osint",
            reasoning_prompt="source reasoning",
            draft_prompt="source draft",
            company_search_prompt="source search",
            deep_osint_prompt="source deep osint",
            osint_discovery_mode="hardcore",
            language="English",
            sender_signature_html="<p>Source Sig</p>",
            icp_min_employees=10,
            icp_max_employees=500,
            icp_criteria_json={"industry": ["gaming"]},
        ),
    )
    db.commit()
    return run


def test_clone_wave_copies_setup_and_persona_status_needs_review(db):
    suffix = "clone-ok"
    mailbox = f"persona-b545-{suffix}@example.com"
    persona = Persona(
        slug=f"persona-b545-{suffix}", display_name="Clone Wave Persona", primary_mailbox_email=mailbox,
    )
    db.add(persona)
    db.commit()
    source = _make_source_run(db, suffix, persona_id=persona.id)

    new_run, warnings = clone_wave_run(db, source.id, name=f"Волна 2 — {suffix}")

    assert new_run.id != source.id
    assert new_run.status == "needs_review"
    assert new_run.persona_id == persona.id
    assert new_run.workflow_name == source.workflow_name
    assert new_run.project_id == source.project_id

    new_setup = new_run.run_setup
    assert new_setup is not None
    assert new_setup.prompt_setup_text == "Offer: source offer"
    assert new_setup.critic_canon_text == "source canon"
    assert new_setup.osint_prompt == "source osint"
    assert new_setup.reasoning_prompt == "source reasoning"
    assert new_setup.draft_prompt == "source draft"
    assert new_setup.company_search_prompt == "source search"
    assert new_setup.deep_osint_prompt == "source deep osint"
    assert new_setup.osint_discovery_mode == "hardcore"
    assert new_setup.language == "English"
    assert new_setup.sender_signature_html == "<p>Source Sig</p>"
    assert new_setup.icp_min_employees == 10
    assert new_setup.icp_max_employees == 500
    assert new_setup.icp_criteria_json == {"industry": ["gaming"]}

    # sending_policy configured for this persona's mailbox -> no warning
    from app.models.sending_policy import SendingPolicy

    has_policy = db.query(SendingPolicy).filter(SendingPolicy.mailbox_email == mailbox).first()
    if has_policy is None:
        assert warnings  # мог не быть настроен в снапшоте — тогда честно предупреждает
    else:
        assert warnings == []

    # workflow не запускался — у нового рана нет шагов
    assert list_steps_by_run(db, new_run.id) == []


def test_clone_wave_without_determinable_persona_raises(db):
    """Источник без persona_id и без явного persona_id/persona_slug в запросе — персона не
    определена, клонирование не должно молча повторить граблю run.persona_id=NULL->alexey."""
    suffix = "clone-no-persona"
    source = _make_source_run(db, suffix, persona_id=None)

    with pytest.raises(ValueError, match="Персона не определена"):
        clone_wave_run(db, source.id, name=f"Волна 2 — {suffix}")


def test_clone_wave_source_without_run_setup_raises(db):
    suffix = "clone-no-setup"
    project = Project(name=f"clone-wave-b545-{suffix}", type="generic")
    db.add(project)
    db.commit()
    source = Run(project_id=project.id, workflow_name="generic_outreach", name=f"bare-{suffix}")
    db.add(source)
    db.commit()

    with pytest.raises(ValueError, match="run_setup"):
        clone_wave_run(db, source.id, name=f"Волна 2 — {suffix}", persona_slug="alexey")


def test_clone_wave_nonexistent_project_id_raises_and_creates_nothing(db):
    """Находка код-ревью afe4e2d (B-544/545/546/547): явный project_id, которого нет в БД,
    не должен молча пройти в create_run (FK в SQLite тут выключены) — иначе ран-сирота
    не появляется ни в одном GET /runs/project/{id}."""
    suffix = "clone-bad-project"
    persona = Persona(
        slug=f"persona-b545-{suffix}", display_name="Bad Project Persona", primary_mailbox_email=f"{suffix}@example.com",
    )
    db.add(persona)
    db.commit()
    source = _make_source_run(db, suffix, persona_id=persona.id)
    bogus_project_id = 999_000_111
    run_name = f"Волна 2 — {suffix}"

    with pytest.raises(ValueError, match="Проект"):
        clone_wave_run(db, source.id, name=run_name, project_id=bogus_project_id)

    assert db.query(Run).filter(Run.name == run_name).count() == 0


def test_clone_wave_explicit_persona_slug_overrides_source_persona(db):
    suffix = "clone-override"
    persona_a = Persona(
        slug=f"persona-b545-a-{suffix}", display_name="Persona A", primary_mailbox_email=f"a-{suffix}@example.com",
    )
    persona_b = Persona(
        slug=f"persona-b545-b-{suffix}", display_name="Persona B", primary_mailbox_email=f"b-{suffix}@example.com",
    )
    db.add_all([persona_a, persona_b])
    db.commit()
    source = _make_source_run(db, suffix, persona_id=persona_a.id)

    new_run, _warnings = clone_wave_run(
        db, source.id, name=f"Волна 2 — {suffix}", persona_slug=persona_b.slug,
    )

    assert new_run.persona_id == persona_b.id
