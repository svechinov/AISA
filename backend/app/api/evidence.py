"""Evidence Store endpoints (Phase 2): queryable company evidence with sources."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.run_company import RunCompany
from app.services.evidence_store import (
    backfill_evidence_for_run,
    evidence_summary_for_run,
    list_evidence_for_run_company,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


class EvidenceRow(BaseModel):
    id: int
    kind: str
    fact: str
    source_url: str | None
    confidence: int | None

    class Config:
        from_attributes = True


@router.get("/run-company/{run_company_id}", response_model=list[EvidenceRow])
def list_company_evidence_route(run_company_id: int, db: Session = Depends(get_db)):
    if not db.get(RunCompany, run_company_id):
        raise HTTPException(status_code=404, detail="Run company not found")
    return list_evidence_for_run_company(db, run_company_id)


@router.get("/run/{run_id}/summary")
def evidence_summary_route(run_id: int, db: Session = Depends(get_db)):
    return evidence_summary_for_run(db, run_id)


@router.post("/run/{run_id}/backfill")
def backfill_evidence_route(run_id: int, db: Session = Depends(get_db)):
    """Index dossiers that existed before the Evidence Store (idempotent re-sync)."""
    return backfill_evidence_for_run(db, run_id)
