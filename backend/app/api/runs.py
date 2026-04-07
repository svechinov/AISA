import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.project_repo import get_project
from app.repositories.run_human_ui_repo import get_event_chain_collapsed_map
from app.repositories.run_repo import (
    close_run,
    create_run,
    get_run,
    get_run_for_edit_form,
    get_run_for_workspace_lite,
    list_runs_by_project,
    run_exists,
    update_run_email_style_mode,
    update_run_human_ui_preferences,
    update_run_outreach_fields,
    update_run_project,
    update_run_prompt_setup_text,
    update_run_signature,
)
from app.services.run_context_service import (
    build_master_prompt_text,
    format_search_brief_from_inner,
    get_inner_for_edit_form_relational_only,
    get_prompt_setup_text,
    get_sender_signature_html,
    merge_inner_from_legacy_fields,
    outreach_brief_has_minimum_content,
    parse_outreach_brief_text,
    wrap_context,
)
from app.schemas.run import (
    RetryCompanyFindBody,
    RetryCompanyFindResult,
    RunCardRead,
    RunEditFormRead,
    RunProjectPatch,
    RunCompaniesRead,
    RunEmailStylePatch,
    RunHumanUiPatch,
    RunOutreachPatch,
    RunPromptSetupPatch,
    RunPromptSetupPatchResult,
    RunRead,
    RunReviewSetupFieldsRead,
    RunSignaturePatch,
    RunSignaturePatchResult,
    RunStart,
    RunTrackingStripRead,
    RunWorkspaceLiteRead,
    RunWorkspaceRead,
    RunWorkspaceTickRead,
    run_read_from_orm,
)
from app.services.orchestrator import continue_workflow_after_review, run_workflow
from app.services.replacement_draft_service import generate_replacement_drafts
from app.services.replacement_send_service import send_approved_replacement_drafts
from app.services.run_deletion_service import delete_run_cascade
from app.services.restart_background_jobs import is_restart_in_progress, schedule_restart_background
from app.services.retry_company_find_service import (
    continue_find_for_pending_companies,
    retry_find_for_collected_company,
)
from app.services.run_companies_status_service import get_run_companies_with_status
from app.services.run_display_service import (
    build_run_workspace_lite,
    build_run_workspace_tick,
    enrich_run_for_card,
    get_conversations_snapshot,
    get_prompt_setup_editor_initial_text_for_ui,
    get_run_display_phase,
    get_run_performance_rows,
    get_run_setup_summary,
    get_setup_state_message,
    hourly_send_counts_24h_utc,
    signature_html_has_meaningful_content,
)

router = APIRouter(prefix="/runs", tags=["runs"])
_log = logging.getLogger(__name__)


def _workspace(db, run) -> RunWorkspaceRead:
    rid = run.id
    base = run_read_from_orm(run).model_dump()
    return RunWorkspaceRead(
        **base,
        display_phase=get_run_display_phase(db, run),
        setup_summary=get_run_setup_summary(db, rid),
        setup_steps=[],
        setup_state_message=get_setup_state_message(db, run),
        performance=get_run_performance_rows(db, rid),
        conversations=get_conversations_snapshot(db, rid),
        hourly_sends_24h=hourly_send_counts_24h_utc(db, rid),
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


@router.get("/{run_id}/review-setup-fields", response_model=RunReviewSetupFieldsRead)
def get_run_review_setup_fields_route(run_id: int, db: Session = Depends(get_db)):
    """Lightweight: prompt textarea + signature HTML only (for dialogs — avoids full GET /runs/:id)."""
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    sig = get_sender_signature_html(run) or ""
    return RunReviewSetupFieldsRead(
        prompt_setup_editor_text=get_prompt_setup_editor_initial_text_for_ui(run),
        sender_signature_html=sig,
        prompt_setup_saved=bool(get_prompt_setup_text(run).strip()),
        sender_signature_configured=signature_html_has_meaningful_content(get_sender_signature_html(run)),
    )


@router.get("/{run_id}/edit-form", response_model=RunEditFormRead)
def get_run_edit_form_route(run_id: int, db: Session = Depends(get_db)):
    """
    New/Edit run dialog: scalar run columns + ``run_outreach_context`` only.
    Does not read ``runs.context_json`` or ``input_json`` (see ``get_inner_for_edit_form_relational_only``).
    """
    run = get_run_for_edit_form(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    inner = get_inner_for_edit_form_relational_only(run)
    return RunEditFormRead(
        id=run.id,
        name=run.name,
        notes=run.notes,
        segment=run.segment,
        email_style_mode=run.email_style_mode,
        outreach_brief=format_search_brief_from_inner(inner),
    )


@router.get("/{run_id}/tracking-strip", response_model=RunTrackingStripRead)
def get_run_tracking_strip_route(run_id: int, db: Session = Depends(get_db)):
    """Tracking tab only: signature HTML + ``_human_ui.event_chain_collapsed`` — no full ``RunRead``."""
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    sig = get_sender_signature_html(run) or ""
    chain = get_event_chain_collapsed_map(db, run_id)
    ctx: dict = {}
    if chain:
        ctx["_human_ui"] = {"event_chain_collapsed": {str(k): bool(v) for k, v in chain.items()}}
    return RunTrackingStripRead(sender_signature_html=sig, context_json=ctx)


@router.get("/{run_id}/workspace-lite", response_model=RunWorkspaceLiteRead)
def run_workspace_lite_route(run_id: int, db: Session = Depends(get_db)):
    """Light dashboard refresh: phase, setup_summary counts, performance, conversations, hourly chart (no run row / contacts / drafts)."""
    run = get_run_for_workspace_lite(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunWorkspaceLiteRead(**build_run_workspace_lite(db, run))


@router.get("/{run_id}/workspace-tick", response_model=RunWorkspaceTickRead)
def run_workspace_tick_route(run_id: int, db: Session = Depends(get_db)):
    """Metrics poll: phase + setup_summary + performance only — skips hourly scan and conversation/reminder aggregates."""
    run = get_run_for_workspace_lite(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunWorkspaceTickRead(**build_run_workspace_tick(db, run))


@router.get("/{run_id}/companies", response_model=RunCompaniesRead)
def run_companies_route(
    run_id: int,
    limit: int | None = Query(
        None,
        ge=1,
        le=5000,
        description="If set, returns one page of companies and companies_total for the filtered set.",
    ),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Filter companies by name or website (substring, case-insensitive)."),
    db: Session = Depends(get_db),
):
    """
    Companies table for Human UI.

    Does **not** query the ``contacts`` table and does **not** call ``get_kv_maps_for_entities`` for
    ``run_companies`` (uses ``iter_run_company_table_rows`` — row columns + ``extra_json``).

    Row-level ``contact_status`` is read from the ``run_companies.contact_status`` column when set by
    the worker or retry path (``recompute_and_persist_contact_statuses_for_run``). Otherwise the API returns
    ``pending`` / ``llm_error`` / ``unknown`` without loading contacts.

    If ``run_companies`` is empty, legacy fallback may read the collect step payload via
    ``effective_step_output_json`` (can touch step ``entity_kv`` — rare after migration).
    """
    t_route0 = time.perf_counter()
    if not run_exists(db, run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    get_run_ms = (time.perf_counter() - t_route0) * 1000
    t_svc0 = time.perf_counter()
    data = get_run_companies_with_status(db, run_id, limit=limit, offset=offset, q=q)
    service_call_ms = (time.perf_counter() - t_svc0) * 1000
    total_route_ms = (time.perf_counter() - t_route0) * 1000
    _log_method = _log.info if total_route_ms >= 500.0 else _log.debug
    _log_method(
        "run_companies_route rid=%s limit=%s offset=%s q=%r get_run_ms=%.2f "
        "service_call_ms=%.2f total_route_ms=%.2f",
        run_id,
        limit,
        offset,
        q,
        get_run_ms,
        service_call_ms,
        total_route_ms,
    )
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


@router.patch("/{run_id}/outreach", response_model=RunEditFormRead)
def patch_run_outreach_route(
    run_id: int,
    payload: RunOutreachPatch,
    db: Session = Depends(get_db),
):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is closed")

    seg = (payload.segment or "").strip()
    if not seg:
        raise HTTPException(status_code=400, detail="Region / Country / State is required")

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
    if not outreach_brief_has_minimum_content(inner):
        legacy = ""
        if getattr(run, "input_goal", None):
            legacy = str(run.input_goal).strip()
        if legacy:
            inner["goal"] = legacy
    if not outreach_brief_has_minimum_content(inner):
        raise HTTPException(
            status_code=400,
            detail="Outreach brief must include searchable content (reason for search, field of activity, "
            "or other labeled sections), or legacy Offer/Goal / input_goal.",
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
            email_style_mode=payload.email_style_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Run not found")
    inner_saved = get_inner_for_edit_form_relational_only(updated)
    return RunEditFormRead(
        id=updated.id,
        name=updated.name,
        notes=updated.notes,
        segment=updated.segment,
        email_style_mode=updated.email_style_mode,
        outreach_brief=format_search_brief_from_inner(inner_saved),
    )


@router.patch("/{run_id}/email-style", response_model=RunEditFormRead)
def patch_run_email_style_route(
    run_id: int,
    payload: RunEmailStylePatch,
    db: Session = Depends(get_db),
):
    from app.services.email_style_service import VALID_PROFESSIONAL_PROFILES

    raw = payload.email_style_mode
    try:
        updated = update_run_email_style_mode(
            db,
            run_id,
            None if raw is None or str(raw).strip() == "" else str(raw).strip(),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"{str(e)} Allowed values: {', '.join(sorted(VALID_PROFESSIONAL_PROFILES))}",
        ) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Run not found")
    inner = get_inner_for_edit_form_relational_only(updated)
    return RunEditFormRead(
        id=updated.id,
        name=updated.name,
        notes=updated.notes,
        segment=updated.segment,
        email_style_mode=updated.email_style_mode,
        outreach_brief=format_search_brief_from_inner(inner),
    )


@router.patch("/{run_id}/close", response_model=RunRead)
def close_run_route(run_id: int, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Run is already closed")
    close_run(db, run_id)
    run_after = get_run(db, run_id)
    if not run_after:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_read_from_orm(run_after)


@router.post("/{run_id}/restart")
def restart_run_route(run_id: int, db: Session = Depends(get_db)):
    """
    Queue collect → find → validate again on top of existing data (same brief).
    Returns 202 immediately; work runs in a background thread so other API calls and runs stay usable.
    """
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.closed_at is not None:
        raise HTTPException(status_code=400, detail="Cannot restart a closed run")
    if is_restart_in_progress(run_id):
        raise HTTPException(
            status_code=409,
            detail="Continue outreach is already running for this run",
        )
    # Move off needs_review before returning 202 so clients do not mistake "still reviewing" for "job done".
    run.status = "pending"
    run.finished_at = None
    db.add(run)
    db.commit()
    if not schedule_restart_background(run_id):
        raise HTTPException(
            status_code=409,
            detail="Continue outreach is already running for this run",
        )
    return JSONResponse(
        status_code=202,
        content={"accepted": True, "run_id": run_id},
    )


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
    if not outreach_brief_has_minimum_content(inner):
        legacy = (payload.input_json or {}).get("goal") if isinstance(payload.input_json, dict) else ""
        if legacy:
            inner["goal"] = str(legacy).strip()
    if not inner.get("notes") and payload.notes:
        inner["notes"] = payload.notes.strip()

    if not outreach_brief_has_minimum_content(inner):
        raise HTTPException(
            status_code=400,
            detail="Outreach brief must include searchable content (reason for search, field of activity, "
            "or other labeled sections), or legacy Offer/Goal / input_json.goal.",
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
    r = get_run(db, run.id)
    if not r:
        raise HTTPException(status_code=500, detail="Run not found after start")
    return run_read_from_orm(r)


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

    r = get_run(db, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_read_from_orm(r)


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


@router.patch("/{run_id}/signature", response_model=RunSignaturePatchResult)
def patch_run_signature_route(run_id: int, payload: RunSignaturePatch, db: Session = Depends(get_db)):
    run = update_run_signature(db, run_id, payload.signature_html.strip() or None)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunSignaturePatchResult(
        id=run.id,
        sender_signature_configured=signature_html_has_meaningful_content(get_sender_signature_html(run)),
    )


@router.patch("/{run_id}/prompt-setup", response_model=RunPromptSetupPatchResult)
def patch_run_prompt_setup_route(run_id: int, payload: RunPromptSetupPatch, db: Session = Depends(get_db)):
    run = update_run_prompt_setup_text(db, run_id, payload.prompt_setup_text)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunPromptSetupPatchResult(
        id=run.id,
        prompt_setup_saved=bool(get_prompt_setup_text(run).strip()),
    )


@router.patch("/{run_id}/human-ui", response_model=RunRead)
def patch_run_human_ui_route(run_id: int, payload: RunHumanUiPatch, db: Session = Depends(get_db)):
    run = update_run_human_ui_preferences(
        db,
        run_id,
        event_chain_collapsed=payload.event_chain_collapsed,
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_read_from_orm(run)


@router.patch("/{run_id}/project", response_model=RunRead)
def patch_run_project_route(run_id: int, payload: RunProjectPatch, db: Session = Depends(get_db)):
    """Attach run to a project (fixes empty sidebar when project_id drifted)."""
    try:
        updated = update_run_project(db, run_id, payload.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not updated:
        raise HTTPException(status_code=404, detail="Run not found or target project not found")
    return run_read_from_orm(updated)


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
    return run_read_from_orm(run)
