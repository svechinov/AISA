"""Cross-run company exclusion registry (B-264) — company-level twin of /suppression."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.excluded_company import EXCLUDE_REASON_MANUAL
from app.repositories.excluded_company_repo import (
    add_excluded_company,
    delete_excluded_company,
    is_company_excluded,
    list_excluded_companies,
)

router = APIRouter(prefix="/excluded-companies", tags=["excluded-companies"])


class ExcludedCompanyCreate(BaseModel):
    name: str | None = None
    website: str | None = None
    reason: str = EXCLUDE_REASON_MANUAL
    note: str | None = None
    source_run_id: int | None = None


def _to_dict(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "domain": row.domain,
        "name_key": row.name_key,
        "reason": row.reason,
        "note": row.note,
        "source_run_id": row.source_run_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_excluded_companies_route(db: Session = Depends(get_db)):
    return {"items": [_to_dict(r) for r in list_excluded_companies(db)]}


@router.get("/check")
def check_excluded_company_route(
    name: str | None = None, website: str | None = None, db: Session = Depends(get_db)
):
    hit = is_company_excluded(db, name, website)
    return {
        "name": name,
        "website": website,
        "excluded": hit is not None,
        "entry": _to_dict(hit) if hit is not None else None,
    }


@router.post("", status_code=201)
def add_excluded_company_route(payload: ExcludedCompanyCreate, db: Session = Depends(get_db)):
    row = add_excluded_company(
        db,
        name=payload.name,
        website=payload.website,
        reason=payload.reason,
        note=payload.note,
        source_run_id=payload.source_run_id,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="name or website is required")
    return _to_dict(row)


@router.delete("/{entry_id}", status_code=204)
def delete_excluded_company_route(entry_id: int, db: Session = Depends(get_db)):
    """Un-exclude a company (wrongly excluded). Past runs are not touched — only future collection."""
    if not delete_excluded_company(db, entry_id):
        raise HTTPException(status_code=404, detail="Excluded company not found")
