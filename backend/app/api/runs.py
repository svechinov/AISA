from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.project_repo import get_project
from app.repositories.run_repo import close_run, create_run, get_run, list_runs_by_project
from app.services.run_context_service import (
    build_master_prompt_text,
    merge_inner_from_legacy_fields,
    parse_outreach_brief_text,
    wrap_context,
)
from app.schemas.run import RunCardRead, RunRead, RunStart, RunWorkspaceRead
from app.services.orchestrator import continue_workflow_after_review, run_workflow
from app.services.replacement_draft_service import generate_replacement_drafts
from app.services.replacement_send_service import send_approved_replacement_drafts
from app.services.run_display_service import (
    enrich_run_for_card,
    get_conversations_snapshot,
    get_run_display_phase,
    get_run_performance_rows,
    get_run_setup_summary,
    get_setup_state_message,
    setup_steps_for_run,
)

router = APIRouter(prefix="/runs", tags=["runs"])


def _workspace(db, run) -> RunWorkspaceRead:
    rid = run.id
    base = RunRead.model_validate(run).model_dump()
    return RunWorkspaceRead(
        **base,
        display_phase=get_run_display_phase(db, run),
        setup_summary=get_run_setup_summary(db, rid),
        setup_steps=setup_steps_for_run(db, rid),
        setup_state_message=get_setup_state_message(db, run),
        performance=get_run_performance_rows(db, rid),
        conversations=get_conversations_snapshot(db, rid),
    )


@router.get("/project/{project_id}", response_model=list[RunCardRead])
def list_runs_for_project_route(project_id: int, db: Session = Depends(get_db)):
    runs = list_runs_by_project(db, project_id)
    return [RunCardRead(**enrich_run_for_card(db, r)) for r in runs]


@router.get("/{run_id}/workspace", response_model=RunWorkspaceRead)
def run_workspace_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _workspace(db, run)


@router.patch("/{run_id}/close", response_model=RunRead)
def close_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is already closed")
    close_run(db, run_id)
    return get_run(db, run_id)


@router.post("/start", response_model=RunRead)
def start_run_route(payload: RunStart, db: Session = Depends(get_db)):
    project = get_project(db, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    parsed = parse_outreach_brief_text(payload.outreach_brief)
    inner = merge_inner_from_legacy_fields(
        parsed,
        product=payload.product,
        target_entities=payload.target_entities,
        target_roles=payload.target_roles,
        outreach_goal=payload.outreach_goal,
        tone=payload.tone,
        extra_context=payload.extra_context,
    )
    if not (inner.get("goal") or inner.get("offer")):
        legacy = (payload.input_json or {}).get("goal") if isinstance(payload.input_json, dict) else ""
        if legacy:
            inner["goal"] = str(legacy).strip()
    if not inner.get("notes") and payload.notes:
        inner["notes"] = payload.notes.strip()

    if not (inner.get("goal") or inner.get("offer")):
        raise HTTPException(
            status_code=400,
            detail="Outreach brief must include at least Offer or Goal (or input_json.goal).",
        )

    master = build_master_prompt_text(inner)
    input_json = dict(payload.input_json) if payload.input_json else {}
    if inner.get("goal"):
        input_json.setdefault("goal", inner["goal"])

    run = create_run(
        db,
        project_id=payload.project_id,
        workflow_name=payload.workflow_name,
        input_json=input_json,
        name=payload.name,
        notes=payload.notes,
        segment=payload.segment,
        context_json=wrap_context(inner),
        master_prompt=master,
    )

    run_workflow(db, run.id)
    return get_run(db, run.id)


@router.post("/{run_id}/continue", response_model=RunRead)
def continue_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Cannot continue a closed run")

    try:
        continue_workflow_after_review(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return get_run(db, run_id)


@router.post("/{run_id}/generate-replacement-drafts")
def generate_replacement_drafts_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        return generate_replacement_drafts(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{run_id}/send-replacement-drafts")
def send_replacement_drafts_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        return send_approved_replacement_drafts(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{run_id}", response_model=RunRead)
def get_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
