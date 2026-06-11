"""AI-fit judge prompt: prospect-aware framing (pilot finding — buyers vs offer-industry)."""

import app.services.run_company_ai_fit_service as svc
from app.repositories.project_repo import create_project
from app.repositories.run_repo import (
    create_run,
    get_run,
    update_run_outreach_fields,
    update_run_prompt_setup,
)


def _make_run(db, with_offer=True):
    proj = create_project(db, name="JudgeTest", type="generic")
    run = create_run(db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    update_run_outreach_fields(
        db, run.id, notes="n", segment="s",
        inner={"offer": "training", "target_entities": "companies buying training",
               "target_roles": "HR", "goal": "call", "tone": "Professional", "notes": ""},
        master_prompt="FG sells corporate training to client companies.",
    )
    if with_offer:
        update_run_prompt_setup(db, run.id, prompt_setup_text="Мы продаём корпоративное обучение.")
    db.commit()
    return get_run(db, run.id)


def test_prompt_frames_prospect_not_offer_industry(db):
    run = _make_run(db)
    p = svc._prompt(run, "ООО АГРОТОРГ (X5)", "x5.ru")
    assert "industry is almost never disqualifying" in p
    assert "COMPETITOR / provider of the SAME offer" in p
    assert "What we SELL" in p
    assert "ООО АГРОТОРГ (X5)" in p


def test_prompt_without_offer_still_builds(db):
    run = _make_run(db, with_offer=False)
    p = svc._prompt(run, "Acme", "")
    assert "plausible PROSPECT" in p and "Acme" in p
