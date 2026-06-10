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
    row = TrainingProgram(
        name=payload.name.strip(),
        description=payload.description,
        target_pains=[p.strip() for p in payload.target_pains if p and p.strip()],
        audience=payload.audience,
        format=payload.format,
        bullets=[b.strip() for b in payload.bullets if b and b.strip()],
        asset_id=payload.asset_id,
        status=payload.status or "active",
    )
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
    data = payload.dict(exclude_unset=True)
    for field in ("target_pains", "bullets"):
        if field in data and data[field] is not None:
            data[field] = [s.strip() for s in data[field] if s and s.strip()]
    if "name" in data and data["name"]:
        data["name"] = data["name"].strip()
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
