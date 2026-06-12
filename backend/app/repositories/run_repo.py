from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, defer, selectinload

from app.models.run import Run
from app.models.run_setup import RunSetup
from app.utils.run_relational_payload import (
    inner_from_context_json_blob,
    persist_run_context_extras_from_blob,
    persist_run_input_from_blob,
    replace_master_email_variants,
    upsert_run_outreach_context_row,
)
from app.repositories.project_repo import get_project
from app.repositories.run_human_ui_repo import merge_event_chain_collapsed


def create_run(
    db: Session,
    project_id: int,
    workflow_name: str,
    input_json: dict,
    name: str | None = None,
    notes: str | None = None,
    segment: str | None = None,
    context_json: dict | None = None,
    master_prompt: str | None = None,
) -> Run:
    run = Run(
        project_id=project_id,
        workflow_name=workflow_name,
        status="pending",
        input_json={},
        name=name,
        notes=notes,
        segment=segment,
        context_json={},
        master_prompt=master_prompt,
    )
    db.add(run)
    db.flush()
    ctx = context_json or {}
    inner = inner_from_context_json_blob(ctx)
    upsert_run_outreach_context_row(db, run.id, inner)
    persist_run_context_extras_from_blob(db, run.id, ctx)
    persist_run_input_from_blob(db, run, input_json or {})
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: int) -> Run | None:
    """Load run for API/workers — legacy JSON columns are deferred (never read unless explicitly accessed)."""
    return (
        db.query(Run)
        .options(
            selectinload(Run.run_setup),
            selectinload(Run.outreach_context),
            selectinload(Run.master_email_variants),
            defer(Run.context_json),
            defer(Run.input_json),
            defer(Run.master_email),
        )
        .filter(Run.id == run_id)
        .first()
    )


def run_exists(db: Session, run_id: int) -> bool:
    """Cheap existence check — no relation loads (use for routes that only need 404 vs ok)."""
    return db.execute(select(Run.id).where(Run.id == run_id)).scalar_one_or_none() is not None


def get_run_for_workspace_lite(db: Session, run_id: int) -> Run | None:
    """Single ``runs`` row, no selectinload — for GET /workspace-lite and metrics polling."""
    return (
        db.query(Run)
        .filter(Run.id == run_id)
        .options(
            defer(Run.context_json),
            defer(Run.input_json),
            defer(Run.master_email),
            defer(Run.master_prompt),
            defer(Run.master_email_body),
            defer(Run.sender_signature_html),
        )
        .first()
    )


def get_run_for_edit_form(db: Session, run_id: int) -> Run | None:
    """Load run + outreach_context only — no run_setup / master_email_variants (faster GET /edit-form)."""
    return (
        db.query(Run)
        .options(
            selectinload(Run.outreach_context),
            # Large JSON/text columns — not needed when run_outreach_context + small columns suffice.
            defer(Run.context_json),
            defer(Run.input_json),
            defer(Run.master_prompt),
            defer(Run.master_email),
            defer(Run.master_email_body),
            defer(Run.sender_signature_html),
        )
        .filter(Run.id == run_id)
        .first()
    )


def list_runs_by_project(db: Session, project_id: int) -> list[Run]:
    return (
        db.query(Run)
        .options(
            selectinload(Run.run_setup),
            selectinload(Run.outreach_context),
            selectinload(Run.master_email_variants),
            defer(Run.context_json),
            defer(Run.input_json),
            defer(Run.master_email),
        )
        .filter(Run.project_id == project_id)
        .order_by(Run.id.desc())
        .all()
    )


def update_run_project(db: Session, run_id: int, project_id: int) -> Run | None:
    """Reassign run to another project (e.g. after DB restore / id drift). Target project must exist and not be archived."""
    run = get_run(db, run_id)
    if not run:
        return None
    proj = get_project(db, project_id)
    if not proj:
        return None
    if proj.is_archived:
        raise ValueError("Cannot move a run to an archived project")
    if run.project_id == project_id:
        return run
    run.project_id = project_id
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def close_run(db: Session, run_id: int) -> Run | None:
    run = get_run(db, run_id)
    if not run:
        return None
    run.closed_at = datetime.utcnow()
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_master_email_variants(
    db: Session,
    run: Run,
    variants: list[dict[str, str]],
) -> Run:
    """Persist canonical outreach variants (relational + legacy columns for first variant)."""
    replace_master_email_variants(db, run.id, list(variants))
    run.master_email = None
    if variants:
        run.master_email_subject = variants[0].get("subject")
        run.master_email_body = variants[0].get("body")
    else:
        run.master_email_subject = None
        run.master_email_body = None
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run_master_email_parts(run: Run) -> tuple[str, str]:
    """First relational variant, else scalar subject/body columns."""
    vs = getattr(run, "master_email_variants", None) or []
    if vs:
        first = sorted(vs, key=lambda x: x.position)[0]
        s = (first.subject or "").strip()
        b = (first.body or "").strip()
        if s and b:
            return s, b
    s2 = (run.master_email_subject or "").strip()
    b2 = (run.master_email_body or "").strip()
    return s2, b2


def _prune_run_setup_if_empty(db: Session, row: RunSetup | None) -> None:
    if row is None:
        return
    if not (row.prompt_setup_text or "").strip() and not (row.sender_signature_html or "").strip():
        db.delete(row)


def update_run_signature(db: Session, run_id: int, signature_html: str | None) -> Run | None:
    run = get_run(db, run_id)
    if not run:
        return None
    sig = (signature_html or "").strip() or None
    row = db.query(RunSetup).filter(RunSetup.run_id == run_id).first()
    if sig is None:
        if row:
            row.sender_signature_html = None
            _prune_run_setup_if_empty(db, row)
    else:
        if row is None:
            row = RunSetup(run_id=run_id)
            db.add(row)
        row.sender_signature_html = sig
    run.sender_signature_html = None
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_human_ui_preferences(
    db: Session,
    run_id: int,
    *,
    event_chain_collapsed: dict[str, bool] | None = None,
) -> Run | None:
    """Persist dashboard UI flags in ``run_event_chain_collapse`` only — does not touch ``runs.context_json``."""
    run = get_run(db, run_id)
    if not run:
        return None
    if event_chain_collapsed is not None:
        merge_event_chain_collapsed(db, run_id, event_chain_collapsed=event_chain_collapsed)
    db.commit()
    db.refresh(run)
    return run


def update_run_prompt_setup(
    db: Session,
    run_id: int,
    *,
    prompt_setup_text: str | None = None,
    osint_prompt: str | None = None,
    reasoning_prompt: str | None = None,
    draft_prompt: str | None = None,
    company_search_prompt: str | None = None,
    deep_osint_prompt: str | None = None,
    osint_discovery_mode: str | None = None,
    language: str | None = None,
    icp_min_employees: int | None = None,
    icp_max_employees: int | None = None,
    icp_criteria_json: dict | None = None,
    icp_unset: bool = False,
) -> Run | None:
    """Persist labeled outreach prompt text and granular AI prompts in ``run_setups``.

    ICP band: pass ints to set, or icp_unset=True to clear a bound to NULL (no limit on that side).
    """
    run = get_run(db, run_id)
    if not run:
        return None
    row = db.query(RunSetup).filter(RunSetup.run_id == run_id).first()
    
    if row is None:
        row = RunSetup(run_id=run_id)
        db.add(row)
    
    if prompt_setup_text is not None:
        row.prompt_setup_text = prompt_setup_text.strip() or None
    if osint_prompt is not None:
        row.osint_prompt = osint_prompt.strip() or None
    if reasoning_prompt is not None:
        row.reasoning_prompt = reasoning_prompt.strip() or None
    if draft_prompt is not None:
        row.draft_prompt = draft_prompt.strip() or None
    if company_search_prompt is not None:
        row.company_search_prompt = company_search_prompt.strip() or None
    if deep_osint_prompt is not None:
        row.deep_osint_prompt = deep_osint_prompt.strip() or None
    if osint_discovery_mode is not None:
        row.osint_discovery_mode = osint_discovery_mode.strip() or "hardcore"
    if language is not None:
        row.language = language.strip() or "Russian"
    if icp_min_employees is not None or icp_unset:
        row.icp_min_employees = icp_min_employees
    if icp_max_employees is not None or icp_unset:
        row.icp_max_employees = icp_max_employees
    if icp_criteria_json is not None:
        row.icp_criteria_json = icp_criteria_json or None

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_prompt_setup_text(db: Session, run_id: int, prompt_setup_text: str) -> Run | None:
    return update_run_prompt_setup(db, run_id, prompt_setup_text=prompt_setup_text)


def update_run_status(db: Session, run: Run, status: str):
    run.status = status

    if status in {"completed", "failed"}:
        run.finished_at = datetime.utcnow()
    else:
        run.finished_at = None

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_outreach_fields(
    db: Session,
    run_id: int,
    *,
    notes: str | None,
    segment: str,
    inner: dict[str, str],
    master_prompt: str,
    email_style_mode: str | None = None,
) -> Run | None:
    """Refresh outreach context row, master_prompt, segment, notes; optional email_style_mode in same commit.

    Does not read ``runs.context_json`` (avoids lazy-loading huge legacy blobs on every save).
    """
    from app.services.email_style_service import normalize_email_style_mode

    run = get_run(db, run_id)
    if not run:
        return None
    if run.closed_at is not None:
        raise ValueError("Cannot update outreach fields on a closed run")

    upsert_run_outreach_context_row(db, run.id, inner)
    run.notes = (notes or "").strip() or None
    run.segment = (segment or "").strip()
    run.master_prompt = master_prompt

    legacy_ij = dict(run.input_json or {})
    if legacy_ij:
        persist_run_input_from_blob(db, run, legacy_ij)
    # Goal from the labeled brief only — do not call persist_run_input_from_blob with {goal}
    # alone: that replaces SCOPE_RUN_INPUT and deletes every other key.
    g_raw = inner.get("goal")
    run.input_goal = str(g_raw).strip() if g_raw is not None and str(g_raw).strip() else None
    run.input_json = {}

    if email_style_mode is not None:
        run.email_style_mode = normalize_email_style_mode(email_style_mode)

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_email_style_mode(db: Session, run_id: int, email_style_mode: str | None) -> Run | None:
    from app.services.email_style_service import normalize_email_style_mode

    run = get_run(db, run_id)
    if not run:
        return None
    if run.closed_at is not None:
        raise ValueError("Cannot update email style on a closed run")
    try:
        norm = normalize_email_style_mode(email_style_mode)
    except ValueError as e:
        raise ValueError(str(e)) from e
    run.email_style_mode = norm
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
