from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.step_repo import get_step, list_steps_by_run
from app.schemas.step import StepRead

router = APIRouter(prefix="/steps", tags=["steps"])


@router.get("/run/{run_id}", response_model=list[StepRead])
def list_steps_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_steps_by_run(db, run_id)


@router.get("/{step_id}", response_model=StepRead)
def get_step_route(step_id: int, db: Session = Depends(get_db)):
    step = get_step(db, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return step
