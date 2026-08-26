"""ICP size-gate inside enrich_crm_data (stubbed firmographics + LLM, 0 tokens)."""

import pytest

import app.workers.osint_worker as ow
from app.models.company_evidence import CompanyEvidence
from app.models.run_company import RunCompany
from app.models.run_setup import RunSetup
from app.repositories.project_repo import create_project
from app.repositories.run_repo import create_run, get_run

RUN_NS = 999_010


@pytest.fixture()
def run_with_band(db):
    proj = create_project(db, name="IcpEnrich", type="generic")
    run = create_run(db, project_id=proj.id, workflow_name="generic_outreach", input_json={})
    db.add(RunSetup(run_id=run.id, osint_discovery_mode="api_only",
                    icp_min_employees=100, icp_max_employees=3000))
    db.commit()
    yield get_run(db, run.id)
    db.query(CompanyEvidence).filter_by(run_id=run.id).delete(synchronize_session=False)
    db.query(RunCompany).filter_by(run_id=run.id).delete(synchronize_session=False)
    db.query(RunSetup).filter_by(run_id=run.id).delete(synchronize_session=False)
    db.commit()


def _company(db, run_id, idx, name):
    rc = RunCompany(run_id=run_id, collect_index=idx, name=name, website=f"{name}.test", extra_json={})
    db.add(rc); db.commit(); return rc


def test_size_gate_rejects_out_of_band_before_judge(db, run_with_band, monkeypatch):
    run = run_with_band
    small = _company(db, run.id, 1, "TinyCo")
    mid = _company(db, run.id, 2, "MidCo")
    big = _company(db, run.id, 3, "GiantCo")
    unknown = _company(db, run.id, 4, "MysteryCo")

    sizes = {"TinyCo": 30, "MidCo": 800, "GiantCo": 50000}  # MysteryCo -> None
    monkeypatch.setattr(ow, "firmographics_configured", lambda: True, raising=False)
    # patch the names imported inside _apply_icp_size_filter
    import app.services.firmographics_service as fs
    monkeypatch.setattr(fs, "firmographics_configured", lambda: True)
    monkeypatch.setattr(fs, "lookup_firmographics",
                        lambda name, website="", inn="": ({"employee_count": sizes[name], "source": "stub"} if name in sizes else None))
    # don't spend on dossiers/discovery — stub them
    monkeypatch.setattr(ow, "get_company_dossier", lambda n, w, run=None: '{"error":"stub"}')
    monkeypatch.setattr(ow, "discover_contact_email", lambda *a, **k: None)

    ow._apply_icp_size_filter(db, run, db.query(RunCompany).filter_by(run_id=run.id).all())
    for c in (small, mid, big, unknown):
        db.refresh(c)
    assert small.ai_fit_status == "incorrect" and "30" in small.ai_fit_reason
    assert big.ai_fit_status == "incorrect"
    assert mid.ai_fit_status is None       # in band -> not rejected, left for judge
    assert unknown.ai_fit_status is None   # unknown size -> not rejected
    # size recorded as evidence for the rejected one (assert by content — shared DB reuses ids)
    facts = [e.fact for e in db.query(CompanyEvidence).filter_by(run_company_id=small.id, kind="trigger").all()]
    assert any("30" in f for f in facts)


def test_no_provider_means_inert_gate(db, run_with_band, monkeypatch):
    run = run_with_band
    c = _company(db, run.id, 5, "NoProvCo")
    import app.services.firmographics_service as fs
    monkeypatch.setattr(fs, "firmographics_configured", lambda: False)
    ow._apply_icp_size_filter(db, run, db.query(RunCompany).filter_by(run_id=run.id).all())
    db.refresh(c)
    assert c.ai_fit_status is None  # gate inert when no firmographics provider
