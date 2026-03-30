from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.rule_repo import create_rule
from app.schemas.rule import RuleCreate, RuleRead

router = APIRouter(prefix="/rules", tags=["rules"])


@router.post("", response_model=RuleRead)
def create_rule_route(payload: RuleCreate, db: Session = Depends(get_db)):
    return create_rule(
        db=db,
        scope=payload.scope,
        content=payload.content,
        project_id=payload.project_id,
        workflow_name=payload.workflow_name,
        step_name=payload.step_name,
        active=payload.active,
    )
