"""Manual fit override (ICP reject-queue) + validate_contacts verification annotations. 0 tokens."""

import pytest

from app.models.run_company import RunCompany
from app.services.run_company_ai_fit_service import set_run_company_fit_manual
from app.workers.contacts_worker import validate_contacts


@pytest.fixture()
def rc(db):
    row = RunCompany(run_id=1, collect_index=9201, name="FitCo (test)", website="fitco.test",
                     ai_fit_status="incorrect", ai_fit_reason="off-target", extra_json={})
    db.add(row)
    db.commit()
    yield row
    db.delete(row)
    db.commit()


def test_manual_override_round_trip(db, rc):
    out = set_run_company_fit_manual(db, 1, rc.collect_index, "correct")
    assert out["ai_fit_status"] == "correct" and out["ai_fit_reason"] == "Manual override"
    db.refresh(rc)
    assert rc.ai_fit_status == "correct"
    set_run_company_fit_manual(db, 1, rc.collect_index, "incorrect")
    db.refresh(rc)
    assert rc.ai_fit_status == "incorrect"


def test_manual_override_rejects_garbage_status(db, rc):
    with pytest.raises(ValueError):
        set_run_company_fit_manual(db, 1, rc.collect_index, "banana")
    with pytest.raises(ValueError):
        set_run_company_fit_manual(db, 1, 777_777, "correct")  # unknown collect_index


def test_validate_keeps_format_semantics_in_default_mode(db, monkeypatch):
    """Default (no strict, no probe): same valid/invalid split as the legacy format check."""
    monkeypatch.delenv("VALIDATE_STRICT", raising=False)
    monkeypatch.delenv("VALIDATE_SMTP_PROBE", raising=False)
    out = validate_contacts(db, 1, "generic_outreach", {"contacts": [
        {"name": "A", "company": "C1", "website": "c1.test", "email": "a@c1.test"},
        {"name": "B", "company": "C2", "website": "c2.test", "email": "not-an-email"},
        {"name": "D", "company": "C3", "website": "c3.test", "email": ""},
    ]})
    valid_emails = {c["email"] for c in out["valid_contacts"]}
    assert valid_emails == {"a@c1.test"}
    assert len(out["invalid_contacts"]) == 2
