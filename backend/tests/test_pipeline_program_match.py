"""Feature 1 wiring: _apply_program_match + meta. PDF is NOT attached to the cold email — the
program lives in the body summary; the PDF is a post-positive-reply follow-up (decision 12.06)."""

import pytest

import app.services.outreach_email_pipeline as oep
import app.services.program_matcher as pm
from app.models.asset import Asset
from app.models.contact import Contact
from app.models.email_draft import EmailDraft
from app.repositories.draft_attachment_repo import list_asset_ids_for_email_draft
from app.services.email_draft_persistence_service import persist_generated_emails
from app.models.training_program import TrainingProgram


class _FakeRun:
    run_setup = None


@pytest.fixture()
def setup(db):
    pdf_a = Asset(asset_type="pdf", name="A.pdf (test-wiring)", status="active", metadata_json={})
    pdf_b = Asset(asset_type="pdf", name="B.pdf (test-wiring)", status="active", metadata_json={})
    db.add_all([pdf_a, pdf_b])
    db.flush()
    prog = TrainingProgram(name="Прог (test-wiring)", target_pains=["боль"], bullets=["б1"],
                           asset_id=pdf_a.id)
    db.add(prog)
    ct = Contact(run_id=1, company="WiringCo (test)", website="wiring.test", name="W T",
                 role="CEO", email="w@wiring.test", status="valid", source_json={})
    db.add(ct)
    db.commit()
    yield {"pdf_a": pdf_a, "pdf_b": pdf_b, "prog": prog, "contact": ct}
    db.query(EmailDraft).filter(EmailDraft.contact_id == ct.id).delete(synchronize_session=False)
    db.delete(ct); db.delete(prog); db.delete(db.get(Asset, pdf_a.id)); db.delete(db.get(Asset, pdf_b.id))
    db.commit()


def test_apply_program_match_keeps_reasoning_strings_and_returns_meta(db, setup, monkeypatch):
    """F7: reasoning slots stay str→str; ids/fit live in the returned meta record only."""
    monkeypatch.setattr(pm, "complete_prompt_json_object", lambda p: {
        "program_id": setup["prog"].id, "fit_score": 80,
        "solution_text": "Решение: Прог", "rationale": "ok",
    })
    reasoning = {"hook": "h", "angle": "a", "problem": "боль", "solution": "generic", "key_point": "generic"}
    match = oep._apply_program_match(db, _FakeRun(), reasoning, {"osint_dossier": "", "person_osint": None})
    assert match and match["asset_id"] == setup["pdf_a"].id
    assert reasoning["solution"] == "Решение: Прог" == reasoning["key_point"]
    assert all(isinstance(v, str) for v in reasoning.values())
    assert "matched_program" not in reasoning


def test_empty_problem_is_noop(db, setup):
    r = {"hook": "", "angle": "", "problem": "", "solution": "g", "key_point": "g"}
    assert oep._apply_program_match(db, _FakeRun(), r, {}) is None
    assert r["solution"] == "g"


def test_cold_draft_has_no_pdf_but_records_program(db, setup):
    """Decision 12.06: the cold email must NOT carry the program PDF (it goes in a follow-up after
    a positive reply); the program is recorded in the draft meta so the PDF can be sent later."""
    ct = setup["contact"]
    meta = {"reasoning": {"solution": "Решение: Прог"},
            "matched_program": {"program_id": setup["prog"].id, "asset_id": setup["pdf_a"].id}}
    out = persist_generated_emails(db, 1, {"emails": [{
        "contact_id": ct.id, "company": ct.company, "to": ct.email,
        "subject": "S", "body": "B " * 80, "generation_meta_json": meta,
    }]})
    assert out["saved_drafts"] == 1
    assert "program_pdfs_attached" not in out  # the auto-attach behavior is gone
    d = db.query(EmailDraft).filter_by(run_id=1, contact_id=ct.id).one()
    assert list_asset_ids_for_email_draft(db, d.id) == []  # NO attachment on the cold draft
    # program still recorded (in the meta blob) so a later materials send knows the PDF
    from app.services.email_draft_persistence_service import matched_program_asset_id
    assert matched_program_asset_id(d.generation_meta_json) == setup["pdf_a"].id


def test_matched_program_asset_id_helper(db, setup):
    from app.services.email_draft_persistence_service import matched_program_asset_id
    assert matched_program_asset_id({"matched_program": {"asset_id": 7}}) == 7
    assert matched_program_asset_id({"matched_program": None}) is None
    assert matched_program_asset_id({}) is None
    assert matched_program_asset_id(None) is None


def test_meta_columns_round_trip(db, setup):
    """F2: problem/solution/matched_program survive the blob→typed-columns conversion."""
    from app.utils.email_draft_generation_meta import (
        apply_generation_meta_to_draft,
        build_generation_meta_json_from_columns,
    )

    d = EmailDraft(run_id=1, contact_id=setup["contact"].id, subject="s", body="b" * 130,
                   status="draft", tracking_status="draft", review_status="pending")
    meta = {
        "reasoning": {"hook": "h", "angle": "a", "problem": "p", "solution": "sol",
                      "cta_type": "c", "key_point": "sol"},
        "matched_program": {"program_id": 5, "asset_id": 7, "fit_score": 80},
        "style_mode": "auto", "pipeline_source": "llm", "validation_retries": 0,
    }
    apply_generation_meta_to_draft(d, meta)
    assert d.reasoning_problem == "p" and d.reasoning_solution == "sol"
    assert d.matched_program_json == {"program_id": 5, "asset_id": 7, "fit_score": 80}
    rebuilt = build_generation_meta_json_from_columns(d)
    assert rebuilt["reasoning"]["problem"] == "p"
    assert rebuilt["reasoning"]["solution"] == "sol"
    assert rebuilt["matched_program"]["asset_id"] == 7
