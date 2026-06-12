"""enrich_crm_data: hardcore default, named-contact discovery (F1), ICP gate (F5). 0 tokens."""

import pytest

import app.workers.osint_worker as ow
from app.models.company_evidence import CompanyEvidence
from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.models.run_setup import RunSetup

GOOD_DOSSIER = '{"evidence": [{"fact": "f", "source_url": "u", "confidence_score": 80}]}'


@pytest.fixture()
def stubs(monkeypatch):
    """Stub every external call; record spend per company/person."""
    calls = {"dossier": [], "gather": [], "find_valid": [], "tavily_guess": []}
    monkeypatch.setattr(ow, "get_company_dossier", lambda n, w, run=None: calls["dossier"].append(n) or GOOD_DOSSIER)
    monkeypatch.setattr(ow, "gather_raw_entities",
                        lambda n, d, custom_prompt=None: calls["gather"].append(n) or {"leaders": [], "email_mask_guess": None})
    monkeypatch.setattr(ow, "find_valid_email",
                        lambda name, domain, mask: calls["find_valid"].append(name) or f"{name.split()[0].lower()}@{domain}")
    monkeypatch.setattr(ow, "discover_contact_email",
                        lambda c, w, n: calls["tavily_guess"].append(n) or None)
    return calls


@pytest.fixture()
def run_without_setup(db):
    """Default mode (no run_setup row) = hardcore."""
    saved = db.query(RunSetup).filter_by(run_id=1).first()
    state = None
    if saved is not None:
        state = {c.name: getattr(saved, c.name) for c in RunSetup.__table__.columns}
        db.delete(saved)
        db.commit()
        db.expire_all()
    yield
    if state is not None:
        db.add(RunSetup(**state))
        db.commit()


def _mk(db, **kw):
    row = Contact(run_id=1, source_json={}, **kw)
    db.add(row)
    db.commit()
    return row


def test_named_contact_without_email_gets_verified_discovery(db, stubs, run_without_setup):
    """F1 (critical): a contact WITH a name but no email must get find_valid_email for that
    person — not be bulk-invalidated."""
    ct = _mk(db, company="NamedCo (test)", website="namedco.test", name="Ivan Petrov",
             role="CEO", email=None, status="needs_discovery")
    rc = RunCompany(run_id=1, collect_index=9101, name="NamedCo (test)", website="namedco.test",
                    extra_json={"osint_dossier": GOOD_DOSSIER})
    db.add(rc)
    db.commit()
    try:
        ow.enrich_crm_data(db, 1, "generic_outreach", {})
        db.refresh(ct)
        assert "Ivan Petrov" in stubs["find_valid"]
        assert ct.status == "valid" and ct.email == "ivan@namedco.test"
        assert ct.source_json.get("email_verification") == "verified"
    finally:
        db.query(CompanyEvidence).filter_by(run_company_id=rc.id).delete(synchronize_session=False)
        db.delete(ct); db.delete(rc); db.commit()


def test_icp_gate_skips_rejected_company_with_name_variants(db, stubs, run_without_setup):
    """F5: gate matches via entity keys (website too), so a name variant can't leak spend."""
    rc_bad = RunCompany(run_id=1, collect_index=9102, name="ООО  Гейт Ко (test)",
                        website="gateco.test", ai_fit_status="incorrect", extra_json={})
    rc_good = RunCompany(run_id=1, collect_index=9103, name="OkCo (test)", website="okco.test",
                         ai_fit_status="correct", extra_json={"osint_dossier": GOOD_DOSSIER})
    # contact's company string differs from the RunCompany name — website must still match
    ct_bad = _mk(db, company="Гейт Ко", website="gateco.test", name="X Y", email=None,
                 status="needs_discovery")
    ct_good = _mk(db, company="OkCo (test)", website="okco.test", name="A B", email=None,
                  status="needs_discovery")
    db.add_all([rc_bad, rc_good])
    db.commit()
    try:
        ow.enrich_crm_data(db, 1, "generic_outreach", {})
        assert "ООО  Гейт Ко (test)" not in stubs["dossier"]   # no dossier spend
        assert "X Y" not in stubs["find_valid"]                # no discovery spend via website key
        assert "A B" in stubs["find_valid"]                    # approved company unaffected
        db.refresh(ct_bad)
        assert ct_bad.status == "needs_discovery"              # untouched, not invalidated
    finally:
        for rc in (rc_bad, rc_good):
            db.query(CompanyEvidence).filter_by(run_company_id=rc.id).delete(synchronize_session=False)
        for o in (ct_bad, ct_good, rc_bad, rc_good):
            db.delete(o)
        db.commit()


def test_api_only_mode_still_uses_tavily_guess(db, stubs):
    """Explicit Cloud Safe mode keeps the legacy unverified path."""
    setup = db.query(RunSetup).filter_by(run_id=1).first()
    created = False
    if setup is None:
        setup = RunSetup(run_id=1, osint_discovery_mode="api_only")
        db.add(setup)
        created = True
    else:
        setup.osint_discovery_mode = "api_only"
    db.commit()
    ct = _mk(db, company="CloudCo (test)", website="cloudco.test", name="C D", email=None,
             status="needs_discovery")
    try:
        ow.enrich_crm_data(db, 1, "generic_outreach", {})
        assert "C D" in stubs["tavily_guess"]
        assert not stubs["gather"] and not stubs["find_valid"]
    finally:
        db.delete(ct)
        if created:
            db.delete(setup)
        db.commit()
