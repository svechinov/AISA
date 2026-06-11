"""Evidence Store: sync, summary, backfill, lifecycle hooks (review fix F3)."""

import json

import pytest

from app.models.company_evidence import CompanyEvidence
from app.models.run_company import RunCompany
from app.services.evidence_store import (
    backfill_evidence_for_run,
    evidence_summary_for_run,
    list_evidence_for_run_company,
    sync_company_evidence_from_dossier,
)
from app.utils.run_company_extra import effective_run_company_extra, persist_run_company_extra

DOSSIER = json.dumps({
    "hypotheses": ["гипотеза"],
    "triggers": ["триггер 1", "триггер 2"],
    "evidence": [
        {"fact": "Выручка выросла", "source_url": "https://rbc.ru/x", "confidence_score": 90},
        {"fact": "Запущена программа", "source_url": "https://k.ru/y", "confidence_score": 60},
        {"fact": "Без источника", "confidence_score": "high"},
        {"no_fact": "skip"},
    ],
}, ensure_ascii=False)


@pytest.fixture()
def rc(db):
    row = RunCompany(run_id=1, collect_index=9001, name="EvCo (test)", website="evco.test",
                     extra_json={})
    db.add(row)
    db.commit()
    yield row
    db.query(CompanyEvidence).filter_by(run_company_id=row.id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()


def test_sync_parses_all_kinds_and_is_idempotent(db, rc):
    assert sync_company_evidence_from_dossier(db, rc, DOSSIER, commit=True) == 6
    rows = list_evidence_for_run_company(db, rc.id)
    ev = [r for r in rows if r.kind == "evidence"]
    assert len(ev) == 3
    assert ev[0].confidence == 90  # ordered high-confidence first
    assert sorted(r.confidence for r in ev if r.confidence is not None) == [60, 90]
    assert any(r.source_url == "https://rbc.ru/x" for r in ev)
    # idempotent replace, not append
    sync_company_evidence_from_dossier(db, rc, DOSSIER, commit=True)
    assert db.query(CompanyEvidence).filter_by(run_company_id=rc.id).count() == 6


def test_malformed_dossier_yields_zero_rows(db, rc):
    assert sync_company_evidence_from_dossier(db, rc, "not json {", commit=True) == 0
    assert sync_company_evidence_from_dossier(db, rc, '{"error": "boom"}', commit=True) == 0


def test_persist_extra_hook_indexes_dossier(db, rc):
    """F3: persist_run_company_extra is the choke point — writing a dossier indexes evidence."""
    kv = effective_run_company_extra(db, rc)
    kv["osint_dossier"] = DOSSIER
    persist_run_company_extra(db, rc, kv)
    db.commit()
    assert db.query(CompanyEvidence).filter_by(run_company_id=rc.id).count() == 6


def test_backfill_and_summary(db, rc):
    kv = effective_run_company_extra(db, rc)
    kv["osint_dossier"] = DOSSIER
    persist_run_company_extra(db, rc, kv)
    db.commit()
    db.query(CompanyEvidence).filter_by(run_company_id=rc.id).delete(synchronize_session=False)
    db.commit()

    out = backfill_evidence_for_run(db, 1)
    assert out["companies_synced"] >= 1
    assert db.query(CompanyEvidence).filter_by(run_company_id=rc.id).count() == 6

    s = evidence_summary_for_run(db, 1)
    assert s["companies_with_evidence"] >= 1
    assert s["facts_total"] >= 3
    assert s["avg_confidence"] is not None


def test_company_resync_purges_orphans(db):
    """F3: re-creating run_companies rows must not leave orphaned evidence
    (SQLite does not enforce the FK cascade)."""
    from app.repositories.run_company_repo import sync_run_companies_from_dicts

    run_id = 999_001  # throwaway run namespace
    sync_run_companies_from_dicts(db, run_id, [
        {"name": "OrphanCo", "website": "orphan.test", "osint_dossier": DOSSIER},
    ])
    first_ids = [r.id for r in db.query(RunCompany).filter_by(run_id=run_id).all()]
    assert db.query(CompanyEvidence).filter_by(run_id=run_id).count() == 6

    # replace all rows (new ids) — evidence must follow, no orphans
    sync_run_companies_from_dicts(db, run_id, [
        {"name": "OrphanCo v2", "website": "orphan.test", "osint_dossier": DOSSIER},
    ])
    rows = db.query(CompanyEvidence).filter_by(run_id=run_id).all()
    new_ids = {r.id for r in db.query(RunCompany).filter_by(run_id=run_id).all()}
    # NB: SQLite may reuse the deleted rowid, so old/new ids can coincide — the meaningful
    # invariant is that every evidence row points at a LIVE company row and counts match.
    assert rows and all(r.run_company_id in new_ids for r in rows)
    assert db.query(CompanyEvidence).filter_by(run_id=run_id).count() == 6
    assert len(first_ids) == 1  # silence unused warning; captured for debugging

    # cleanup
    db.query(CompanyEvidence).filter_by(run_id=run_id).delete(synchronize_session=False)
    db.query(RunCompany).filter_by(run_id=run_id).delete(synchronize_session=False)
    db.commit()
