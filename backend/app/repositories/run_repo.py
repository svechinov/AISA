from datetime import datetime

from sqlalchemy.orm import Session, selectinload

from app.models.run import Run
from app.models.run_setup import RunSetup
from app.repositories.project_repo import get_project
from app.services.run_context_service import wrap_context


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
        input_json=input_json,
        name=name,
        notes=notes,
        segment=segment,
        context_json=context_json or {},
        master_prompt=master_prompt,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run(db: Session, run_id: int) -> Run | None:
    return (
        db.query(Run)
        .options(selectinload(Run.run_setup))
        .filter(Run.id == run_id)
        .first()
    )


def list_runs_by_project(db: Session, project_id: int) -> list[Run]:
    return (
        db.query(Run)
        .options(selectinload(Run.run_setup))
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
    """Persist canonical outreach: run.master_email = {\"variants\": [...]}."""
    run.master_email = {"variants": list(variants)}
    if variants:
        run.master_email_subject = variants[0]["subject"]
        run.master_email_body = variants[0]["body"]
    else:
        run.master_email_subject = None
        run.master_email_body = None
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run_master_email_parts(run: Run) -> tuple[str, str]:
    """First variant (or legacy flat master_email / columns) for non-send utilities."""
    me = getattr(run, "master_email", None) or {}
    if isinstance(me, dict):
        vlist = me.get("variants")
        if isinstance(vlist, list) and vlist:
            first = vlist[0]
            if isinstance(first, dict):
                s = (first.get("subject") or "").strip()
                b = (first.get("body") or "").strip()
                if s and b:
                    return s, b
        s = (me.get("subject") or "").strip()
        b = (me.get("body") or "").strip()
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


# Legacy key removed from context_json on save; canonical store is run_setups.prompt_setup_text.
_PROMPT_SETUP_JSON_KEY = "prompt_setup_text"
_HUMAN_UI_JSON_KEY = "_human_ui"


def update_run_human_ui_preferences(
    db: Session,
    run_id: int,
    *,
    event_chain_collapsed: dict[str, bool] | None = None,
) -> Run | None:
    """Persist dashboard UI flags (per-draft event chain collapse, etc.)."""
    run = get_run(db, run_id)
    if not run:
        return None
    ctx = dict(run.context_json or {})
    ui = dict(ctx.get(_HUMAN_UI_JSON_KEY) or {})
    if event_chain_collapsed is not None:
        chain = dict(ui.get("event_chain_collapsed") or {})
        for k, v in event_chain_collapsed.items():
            sk = str(k).strip()
            if not sk:
                continue
            chain[sk] = bool(v)
        ui["event_chain_collapsed"] = chain
    ctx[_HUMAN_UI_JSON_KEY] = ui
    run.context_json = ctx
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_prompt_setup_text(db: Session, run_id: int, prompt_setup_text: str) -> Run | None:
    """Persist labeled outreach prompt text in run_setups; empty removes it. Legacy context_json key cleared."""
    run = get_run(db, run_id)
    if not run:
        return None
    row = db.query(RunSetup).filter(RunSetup.run_id == run_id).first()
    if (prompt_setup_text or "").strip() == "":
        if row:
            row.prompt_setup_text = None
            _prune_run_setup_if_empty(db, row)
    else:
        if row is None:
            row = RunSetup(run_id=run_id)
            db.add(row)
        row.prompt_setup_text = prompt_setup_text
    ctx = dict(run.context_json or {})
    ctx.pop(_PROMPT_SETUP_JSON_KEY, None)
    run.context_json = ctx
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


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
) -> Run | None:
    """Refresh context.context, master_prompt, segment, notes; keep _human_ui (prompt lives in run_setups)."""
    run = get_run(db, run_id)
    if not run:
        return None
    if run.closed_at is not None:
        raise ValueError("Cannot update outreach fields on a closed run")

    wrapped = wrap_context(inner)
    ctx = dict(run.context_json or {})
    ctx["context"] = wrapped["context"]

    run.context_json = ctx
    run.notes = (notes or "").strip() or None
    run.segment = (segment or "").strip()
    run.master_prompt = master_prompt

    ij = dict(run.input_json or {})
    if inner.get("goal"):
        ij["goal"] = inner["goal"]
    run.input_json = ij

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run_email_style_mode(db: Session, run_id: int, email_style_mode: str | None) -> Run | None:
    run = get_run(db, run_id)
    if not run:
        return None
    if run.closed_at is not None:
        raise ValueError("Cannot update email style on a closed run")
    m = (email_style_mode or "").strip().lower()
    run.email_style_mode = m if m else None
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
