from datetime import datetime

from sqlalchemy.orm import Session

from app.models.run import Run


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
    return db.query(Run).filter(Run.id == run_id).first()


def list_runs_by_project(db: Session, project_id: int) -> list[Run]:
    return (
        db.query(Run)
        .filter(Run.project_id == project_id)
        .order_by(Run.id.desc())
        .all()
    )


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
