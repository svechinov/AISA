"""Fork-transition Phase 1, Tasks 7-8: scripts/seed_noda12_preset.py seeds the "noda12" persona,
the (6-session, see module docstring) offer catalog, and two RunSetup profiles (consulting / trek A
vs corporate / trek B) on top of the same persona. Tests the internal building blocks directly
(same convention as test_seed_alexstaff_preset_profile_b128.py) rather than invoking main(), since
main() opens its own SessionLocal() bound to the process DATABASE_URL, not the isolated fresh_db
engine. 0 tokens: no LLM."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_noda12_preset as seed  # noqa: E402
from app.models.run_setup import RunSetup  # noqa: E402
from app.models.training_program import TrainingProgram  # noqa: E402
from app.services.persona_service import NODA12_SLUG, get_run_persona  # noqa: E402
from app.repositories.project_repo import create_project  # noqa: E402
from app.repositories.run_repo import create_run  # noqa: E402


# ---------------------------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------------------------


def test_seed_persona_noda12_creates_row(fresh_db):
    persona = seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    assert persona.slug == NODA12_SLUG
    assert persona.no_signal_template_enabled is False
    assert persona.languages_json == ["Russian"]


def test_seed_persona_noda12_idempotent(fresh_db):
    seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    from app.models.persona import Persona

    rows = fresh_db.query(Persona).filter(Persona.slug == NODA12_SLUG).all()
    assert len(rows) == 1


def test_get_run_persona_returns_noda12_not_alexey(fresh_db):
    persona = seed._seed_persona_noda12(fresh_db)
    fresh_db.commit()
    proj = create_project(fresh_db, name="Noda12PersonaTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    run.persona_id = persona.id
    fresh_db.commit()

    resolved = get_run_persona(fresh_db, run)
    assert resolved.slug == NODA12_SLUG


# ---------------------------------------------------------------------------------------------
# Offer catalog
# ---------------------------------------------------------------------------------------------


def test_seed_offers_creates_expected_count(fresh_db):
    seed._seed_offers(fresh_db)
    fresh_db.commit()
    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)
    names = {r.name for r in rows}
    assert "Пивная игра (bullwhip-эффект)" in names
    assert "SIR-волна (эпидемия как система)" in names
    assert "Карантинная честность (переговорная, 3 игрока)" in names


def test_seed_offers_idempotent_by_name(fresh_db):
    seed._seed_offers(fresh_db)
    fresh_db.commit()
    seed._seed_offers(fresh_db)
    fresh_db.commit()
    rows = fresh_db.query(TrainingProgram).all()
    assert len(rows) == len(seed.OFFERS)


def test_every_offer_has_non_empty_target_pains_and_bullets():
    """The matcher needs non-empty target_pains/bullets to have anything to score against."""
    for offer in seed.OFFERS:
        assert offer["target_pains"], offer["name"]
        assert offer["bullets"], offer["name"]
        assert offer["audience"]
        assert offer["format"]


# ---------------------------------------------------------------------------------------------
# Two profiles
# ---------------------------------------------------------------------------------------------


def test_consulting_and_corporate_profiles_differ():
    consulting_text, consulting_scalar = seed._canon_fields_for_profile("consulting")
    corporate_text, corporate_scalar = seed._canon_fields_for_profile("corporate")

    assert consulting_text["prompt_setup_text"] != corporate_text["prompt_setup_text"]
    assert "trek A" in consulting_text["prompt_setup_text"]
    assert "trek B" in corporate_text["prompt_setup_text"]

    assert consulting_scalar["icp_min_employees"] == 1
    assert consulting_scalar["icp_max_employees"] == 200
    assert corporate_scalar["icp_min_employees"] == 500
    assert corporate_scalar["icp_max_employees"] is None


def test_consulting_profile_overrides_fit_exclusion_rules():
    from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES

    text_fields, _ = seed._canon_fields_for_profile("consulting")
    assert text_fields["fit_exclusion_rules_text"] != DEFAULT_FIT_EXCLUSION_RULES
    assert "training/consulting" in text_fields["fit_exclusion_rules_text"]
    assert "exactly who we sell TO" in text_fields["fit_exclusion_rules_text"]


def test_corporate_profile_keeps_default_fit_exclusion_rules():
    from app.services.run_company_ai_fit_service import DEFAULT_FIT_EXCLUSION_RULES

    text_fields, _ = seed._canon_fields_for_profile("corporate")
    assert text_fields["fit_exclusion_rules_text"] == DEFAULT_FIT_EXCLUSION_RULES


def test_both_profiles_share_the_same_signature():
    """Same persona (noda12), two RunSetup profiles — signature must not diverge by track."""
    consulting_text, _ = seed._canon_fields_for_profile("consulting")
    corporate_text, _ = seed._canon_fields_for_profile("corporate")
    assert consulting_text["sender_signature_html"] == corporate_text["sender_signature_html"]


def test_writing_both_profiles_to_same_run_produces_different_run_setup_state(fresh_db):
    """End-to-end: syncing 'consulting' then 'corporate' onto the SAME run actually changes the
    persisted RunSetup row each time (proves the profiles are not silently identical in practice,
    not just in the in-memory dicts)."""
    proj = create_project(fresh_db, name="Noda12ProfileTest", type="generic")
    run = create_run(fresh_db, project_id=proj.id, workflow_name="generic_outreach", input_json={})

    text_a, scalar_a = seed._canon_fields_for_profile("consulting")
    setup = RunSetup(run_id=run.id)
    fresh_db.add(setup)
    for field, value in {**text_a, **scalar_a}.items():
        setattr(setup, field, value)
    fresh_db.commit()
    assert setup.icp_min_employees == 1

    text_b, scalar_b = seed._canon_fields_for_profile("corporate")
    for field, value in {**text_b, **scalar_b}.items():
        setattr(setup, field, value)
    fresh_db.commit()
    fresh_db.refresh(setup)
    assert setup.icp_min_employees == 500
    assert setup.prompt_setup_text == seed.PROMPT_SETUP_TEXT_CORPORATE
