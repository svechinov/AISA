from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.project_repo import get_project
from app.repositories.run_repo import (
    close_run,
    create_run,
    get_run,
    list_runs_by_project,
    update_run_human_ui_preferences,
    update_run_outreach_fields,
    update_run_prompt_setup_text,
    update_run_signature,
)
from app.services.run_context_service import (
    build_master_prompt_text,
    merge_inner_from_legacy_fields,
    parse_outreach_brief_text,
    wrap_context,
)
from app.schemas.run import (
    RetryCompanyFindBody,
    RetryCompanyFindResult,
    RunCardRead,
    RunCompaniesRead,
    RunHumanUiPatch,
    RunOutreachPatch,
    RunPromptSetupPatch,
    RunRead,
    RunSignaturePatch,
    RunStart,
    RunWorkspaceRead,
)
from app.services.orchestrator import continue_workflow_after_review, run_workflow
from app.services.replacement_draft_service import generate_replacement_drafts
from app.services.replacement_send_service import send_approved_replacement_drafts
from app.services.run_deletion_service import delete_run_cascade
from app.services.run_restart_service import restart_run_workflow
from app.services.retry_company_find_service import (
    continue_find_for_pending_companies,
    retry_find_for_collected_company,
)
from app.services.run_companies_status_service import get_run_companies_with_status
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


@router.get("/{run_id}/companies", response_model=RunCompaniesRead)
def run_companies_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    data = get_run_companies_with_status(db, run_id)
    return RunCompaniesRead(**data)


@router.post("/{run_id}/companies/retry-find", response_model=RetryCompanyFindResult)
def retry_company_find_route(
    run_id: int,
    payload: RetryCompanyFindBody,
    db: Session = Depends(get_db),
):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        data = retry_find_for_collected_company(db, run_id, payload.collect_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RetryCompanyFindResult(**data)


@router.post("/{run_id}/companies/continue-find", response_model=RetryCompanyFindResult)
def continue_company_find_route(run_id: int, db: Session = Depends(get_db)):
    """Find contacts for all companies still 'Not searched yet' (find step not completed); then complete find/validate."""
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        data = continue_find_for_pending_companies(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RetryCompanyFindResult(**data)


@router.patch("/{run_id}/outreach", response_model=RunRead)
def patch_run_outreach_route(run_id: int, payload: RunOutreachPatch, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is closed")

    seg = (payload.segment or "").strip()
    if not seg:
        raise HTTPException(status_code=400, detail="Segment is required")

    parsed = parse_outreach_brief_text(payload.outreach_brief)
    inner = merge_inner_from_legacy_fields(
        parsed,
        product="",
        target_entities="",
        target_roles="",
        outreach_goal="",
        tone="Professional",
        extra_context="",
    )
    if not inner.get("notes") and payload.notes:
        inner["notes"] = payload.notes.strip()
    if not (inner.get("goal") or inner.get("offer")):
        legacy = (run.input_json or {}).get("goal") if isinstance(run.input_json, dict) else ""
        if legacy:
            inner["goal"] = str(legacy).strip()
    if not (inner.get("goal") or inner.get("offer")):
        raise HTTPException(
            status_code=400,
            detail="Outreach brief must include at least Offer or Goal (or input_json.goal).",
        )

    master = build_master_prompt_text(inner)
    try:
        updated = update_run_outreach_fields(
            db,
            run_id,
            notes=payload.notes,
            segment=seg,
            inner=inner,
            master_prompt=master,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Run not found")
    return updated


@router.patch("/{run_id}/close", response_model=RunRead)
def close_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is already closed")
    close_run(db, run_id)
    return get_run(db, run_id)


@router.post("/{run_id}/restart", response_model=RunRead)
def restart_run_route(run_id: int, db: Session = Depends(get_db)):
    """Run collect → find → validate again on top of existing data (same brief); does not wipe contacts/drafts."""
    try:
        restart_run_workflow(db, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


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


@router.patch("/{run_id}/signature", response_model=RunRead)
def patch_run_signature_route(run_id: int, payload: RunSignaturePatch, db: Session = Depends(get_db)):
    run = update_run_signature(db, run_id, payload.signature_html.strip() or None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.patch("/{run_id}/prompt-setup", response_model=RunRead)
def patch_run_prompt_setup_route(run_id: int, payload: RunPromptSetupPatch, db: Session = Depends(get_db)):
    run = update_run_prompt_setup_text(db, run_id, payload.prompt_setup_text)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.patch("/{run_id}/human-ui", response_model=RunRead)
def patch_run_human_ui_route(run_id: int, payload: RunHumanUiPatch, db: Session = Depends(get_db)):
    run = update_run_human_ui_preferences(
        db,
        run_id,
        event_chain_collapsed=payload.event_chain_collapsed,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.delete("/{run_id}", status_code=204)
def delete_run_route(run_id: int, db: Session = Depends(get_db)):
    """Permanently remove a run and all related rows (contacts, drafts, steps, etc.)."""
    if not delete_run_cascade(db, run_id, commit=True):
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/{run_id}", response_model=RunRead)
def get_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
