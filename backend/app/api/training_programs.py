"""CRUD for the training-program catalog (Feature 1: program matcher feeds the solution slot)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.training_program import TrainingProgram
from app.schemas.training_program import (
    TrainingProgramCreate,
    TrainingProgramRead,
    TrainingProgramUpdate,
)

router = APIRouter(prefix="/training-programs", tags=["training-programs"])

ALLOWED_STATUSES = ("active", "archived")


def _normalize_fields(data: dict) -> dict:
    """One normalization rule for create AND update: strip list items / drop empties, strip name,
    validate status (a typo like 'activ' would silently hide the program from the matcher)."""
    for field in ("target_pains", "bullets"):
        if data.get(field) is not None:
            data[field] = [s.strip() for s in data[field] if s and s.strip()]
    if data.get("name") is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="name must not be empty")
    if data.get("status") is not None and data["status"] not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {ALLOWED_STATUSES}")
    return data


@router.get("", response_model=list[TrainingProgramRead])
def list_training_programs_route(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(TrainingProgram)
    if not include_archived:
        q = q.filter(TrainingProgram.status == "active")
    return q.order_by(TrainingProgram.id.asc()).all()


@router.post("", response_model=TrainingProgramRead)
def create_training_program_route(payload: TrainingProgramCreate, db: Session = Depends(get_db)):
    data = _normalize_fields(payload.dict())
    row = TrainingProgram(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{program_id}", response_model=TrainingProgramRead)
def update_training_program_route(
    program_id: int,
    payload: TrainingProgramUpdate,
    db: Session = Depends(get_db),
):
    row = db.get(TrainingProgram, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Training program not found")
    data = _normalize_fields(payload.dict(exclude_unset=True))
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{program_id}")
def archive_training_program_route(program_id: int, db: Session = Depends(get_db)):
    """Soft delete: archive (matcher only considers active programs)."""
    row = db.get(TrainingProgram, program_id)
    if not row:
        raise HTTPException(status_code=404, detail="Training program not found")
    row.status = "archived"
    db.commit()
    return {"status": "archived", "id": program_id}
