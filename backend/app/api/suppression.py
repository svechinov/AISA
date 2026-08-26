from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.suppression_entry import REASON_MANUAL
from app.repositories.suppression_repo import (
    add_suppression,
    delete_suppression,
    is_suppressed,
    list_suppression,
)

router = APIRouter(prefix="/suppression", tags=["suppression"])


class SuppressionCreate(BaseModel):
    email: str
    reason: str = REASON_MANUAL
    source_run_id: int | None = None
    note: str | None = None


def _to_dict(row) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "domain": row.domain,
        "reason": row.reason,
        "source_run_id": row.source_run_id,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_suppression_route(db: Session = Depends(get_db)):
    return {"items": [_to_dict(r) for r in list_suppression(db)]}


@router.get("/check")
def check_suppression_route(email: str, db: Session = Depends(get_db)):
    return {"email": email, "suppressed": is_suppressed(db, email)}


@router.post("", status_code=201)
def add_suppression_route(payload: SuppressionCreate, db: Session = Depends(get_db)):
    if not (payload.email or "").strip():
        raise HTTPException(status_code=400, detail="email is required")
    row = add_suppression(
        db,
        email=payload.email,
        reason=payload.reason,
        source_run_id=payload.source_run_id,
        note=payload.note,
    )
    return _to_dict(row)


@router.delete("/{entry_id}", status_code=204)
def delete_suppression_route(entry_id: int, db: Session = Depends(get_db)):
    """Remove a do-not-contact entry (e.g. a false positive). This does not un-send anything —
    it only lets future sends to this address pass the suppression gate again."""
    if not delete_suppression(db, entry_id):
        raise HTTPException(status_code=404, detail="Suppression entry not found")
