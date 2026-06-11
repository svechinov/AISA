"""Feature 1: program matcher (stubbed LLM, 0 tokens)."""

import pytest

import app.services.program_matcher as pm
from app.models.asset import Asset
from app.models.training_program import TrainingProgram


@pytest.fixture()
def catalog(db):
    pdf = Asset(asset_type="pdf", name="One-Pager (test-matcher)", status="active",
                download_url="https://cdn.example/x.pdf", metadata_json={})
    db.add(pdf)
    db.flush()
    p1 = TrainingProgram(
        name="Системные продажи B2B (test-matcher)",
        target_pains=["слабые продажи", "низкая конверсия"],
        bullets=["воронка", "стандарты"],
        asset_id=pdf.id,
    )
    p2 = TrainingProgram(
        name="Лидерский резерв (test-matcher)",
        target_pains=["кадровый голод"],
        bullets=["оценка потенциала"],
        status="archived",
    )
    db.add_all([p1, p2])
    db.commit()
    yield {"pdf": pdf, "active": p1, "archived": p2}
    db.query(TrainingProgram).filter(TrainingProgram.name.like("%test-matcher%")).delete(
        synchronize_session=False
    )
    db.delete(db.get(Asset, pdf.id))
    db.commit()


def _stub(monkeypatch, response):
    calls = {}

    def fake(prompt):
        calls["prompt"] = prompt
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(pm, "complete_prompt_json_object", fake)
    return calls


def test_match_returns_program_with_asset(db, catalog, monkeypatch):
    calls = _stub(monkeypatch, {
        "program_id": catalog["active"].id, "fit_score": 85,
        "solution_text": "Программа «Системные продажи B2B»", "rationale": "ok",
    })
    m = pm.match_program(db, problem="слабая система продаж")
    assert m and m["program_id"] == catalog["active"].id
    assert m["asset_id"] == catalog["pdf"].id
    assert "Лидерский резерв (test-matcher)" not in calls["prompt"]  # archived excluded


def test_string_typed_ids_from_llm_still_match(db, catalog, monkeypatch):
    """Review fix F6: LLMs string-type numbers; that must not kill the match."""
    _stub(monkeypatch, {
        "program_id": str(catalog["active"].id), "fit_score": "87.5",
        "solution_text": "x", "rationale": "",
    })
    m = pm.match_program(db, problem="боль")
    assert m and m["program_id"] == catalog["active"].id and m["fit_score"] == 87


def test_low_fit_and_null_id_rejected(db, catalog, monkeypatch):
    _stub(monkeypatch, {"program_id": catalog["active"].id, "fit_score": 30,
                        "solution_text": "x", "rationale": ""})
    assert pm.match_program(db, problem="боль") is None
    _stub(monkeypatch, {"program_id": None, "fit_score": 0, "solution_text": "", "rationale": ""})
    assert pm.match_program(db, problem="боль") is None


def test_unknown_id_and_llm_failure_return_none(db, catalog, monkeypatch):
    _stub(monkeypatch, {"program_id": 999999, "fit_score": 90, "solution_text": "x", "rationale": ""})
    assert pm.match_program(db, problem="боль") is None
    _stub(monkeypatch, RuntimeError("llm down"))
    assert pm.match_program(db, problem="боль") is None


def test_empty_catalog_or_problem_is_noop(db, monkeypatch):
    _stub(monkeypatch, {"program_id": 1, "fit_score": 99, "solution_text": "x", "rationale": ""})
    assert pm.match_program(db, problem="") is None
