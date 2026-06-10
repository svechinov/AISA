"""Evidence Store sync + queries (Phase 2): dossier JSON -> company_evidence rows.

Sync is idempotent per company (replace-all) and tolerant: a malformed dossier just yields
zero rows, never an exception — evidence indexing must not break enrichment.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.company_evidence import CompanyEvidence
from app.models.run_company import RunCompany

logger = logging.getLogger(__name__)


def _parse_dossier(dossier: str | dict | None) -> dict[str, Any]:
    if isinstance(dossier, dict):
        return dossier
    if not dossier or not isinstance(dossier, str):
        return {}
    try:
        obj = json.loads(dossier)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def _coerce_confidence(v: Any) -> int | None:
    try:
        n = int(v)
        return max(0, min(100, n))
    except (TypeError, ValueError):
        return None


def sync_company_evidence_from_dossier(
    db: Session,
    run_company: RunCompany,
    dossier: str | dict | None,
    *,
    commit: bool = False,
) -> int:
    """Replace this company's evidence rows with the dossier's content. Returns rows written."""
    rows: list[CompanyEvidence] = []
    obj = _parse_dossier(dossier)

    for item in obj.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        if not fact:
            continue
        rows.append(
            CompanyEvidence(
                run_company_id=run_company.id,
                run_id=run_company.run_id,
                kind="evidence",
                fact=fact,
                source_url=(str(item.get("source_url") or "").strip() or None),
                confidence=_coerce_confidence(item.get("confidence_score", item.get("confidence"))),
            )
        )
    for kind, key in (("hypothesis", "hypotheses"), ("trigger", "triggers")):
        for item in obj.get(key) or []:
            fact = str(item or "").strip()
            if fact:
                rows.append(
                    CompanyEvidence(
                        run_company_id=run_company.id,
                        run_id=run_company.run_id,
                        kind=kind,
                        fact=fact,
                    )
                )

    db.query(CompanyEvidence).filter(
        CompanyEvidence.run_company_id == run_company.id
    ).delete(synchronize_session=False)
    db.flush()  # apply the delete before re-inserting (avoids identity-map collisions)
    if rows:
        db.add_all(rows)
    if commit:
        db.commit()
    return len(rows)


def list_evidence_for_run_company(db: Session, run_company_id: int) -> list[CompanyEvidence]:
    return (
        db.query(CompanyEvidence)
        .filter(CompanyEvidence.run_company_id == run_company_id)
        .order_by(CompanyEvidence.kind.asc(), CompanyEvidence.confidence.desc().nullslast(), CompanyEvidence.id.asc())
        .all()
    )


def evidence_summary_for_run(db: Session, run_id: int) -> dict[str, Any]:
    """Coverage metrics: how grounded is this run's company base."""
    total_companies = db.query(RunCompany).filter(RunCompany.run_id == run_id).count()
    companies_with_evidence = (
        db.query(CompanyEvidence.run_company_id)
        .filter(CompanyEvidence.run_id == run_id, CompanyEvidence.kind == "evidence")
        .distinct()
        .count()
    )
    facts_total = (
        db.query(CompanyEvidence)
        .filter(CompanyEvidence.run_id == run_id, CompanyEvidence.kind == "evidence")
        .count()
    )
    avg_conf = (
        db.query(func.avg(CompanyEvidence.confidence))
        .filter(
            CompanyEvidence.run_id == run_id,
            CompanyEvidence.kind == "evidence",
            CompanyEvidence.confidence.isnot(None),
        )
        .scalar()
    )
    return {
        "run_id": run_id,
        "companies_total": total_companies,
        "companies_with_evidence": companies_with_evidence,
        "facts_total": facts_total,
        "avg_confidence": round(float(avg_conf), 1) if avg_conf is not None else None,
    }


def backfill_evidence_for_run(db: Session, run_id: int) -> dict[str, int]:
    """Index existing dossiers (companies enriched before the Evidence Store existed)."""
    from app.utils.run_company_extra import effective_run_company_extra

    companies = db.query(RunCompany).filter(RunCompany.run_id == run_id).all()
    synced = 0
    rows_written = 0
    for rc in companies:
        kv = effective_run_company_extra(db, rc)
        dossier = kv.get("osint_dossier")
        if not dossier:
            continue
        n = sync_company_evidence_from_dossier(db, rc, dossier)
        if n:
            synced += 1
            rows_written += n
    db.commit()
    logger.info(f"Evidence backfill run {run_id}: {synced} companies, {rows_written} rows")
    return {"companies_synced": synced, "rows_written": rows_written}
