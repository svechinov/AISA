from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.step_repo import get_step, list_steps_by_run
from app.schemas.step import StepRead, step_to_read

router = APIRouter(prefix="/steps", tags=["steps"])


@router.get("/run/{run_id}", response_model=list[StepRead])
def list_steps_for_run(run_id: int, db: Session = Depends(get_db)):
    return [step_to_read(db, s) for s in list_steps_by_run(db, run_id)]


@router.get("/{step_id}", response_model=StepRead)
def get_step_route(step_id: int, db: Session = Depends(get_db)):
    step = get_step(db, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return step_to_read(db, step)


@router.post("/run/{run_id}/execute/{step_name}")
def execute_step_route(run_id: int, step_name: str, db: Session = Depends(get_db)):
    from app.services.orchestrator import execute_step
    try:
        execute_step(db, run_id, step_name)
        return {"status": "completed", "step": step_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
