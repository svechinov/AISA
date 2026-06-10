"""LLM judges whether a collected company fits the run's outreach campaign (one row at a time)."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.run_company import RunCompany
from app.repositories.run_repo import get_run
from app.services.llm_gateway import complete_prompt_json_object, llm_configured
from app.services.run_context_service import build_master_prompt_text, coalesce_str, get_effective_context

logger = logging.getLogger(__name__)


def _prompt(run, company_name: str, company_website: str) -> str:
    ctx = get_effective_context(run)
    brief = build_master_prompt_text(ctx)
    mp = coalesce_str(getattr(run, "master_prompt", None))
    block = f"{mp}\n\n---\n{brief}" if mp else brief
    return (
        "You evaluate whether a REAL company is a plausible target for THIS specific outreach campaign.\n\n"
        "A company is **incorrect** if it clearly cannot match what the campaign seeks "
        "(e.g. a venture accelerator when the campaign seeks backpack manufacturers; "
        "a museum gift shop when the campaign seeks OEM/licensing manufacturers), "
        "based only on public knowledge and the company name + website domain.\n\n"
        "Return ONLY valid JSON (no markdown) with this exact shape:\n"
        '{"fit": true or false, "reason": "one short English sentence"}\n\n'
        "- fit=true: the company could reasonably be a target for this campaign.\n"
        "- fit=false: the company is clearly off-target or irrelevant.\n\n"
        f"Company name: {company_name}\n"
        f"Website: {company_website or '—'}\n\n"
        "Campaign context:\n"
        f"{block}\n"
    )


def analyze_run_company_fit(
    db: Session,
    run_id: int,
    collect_index: int,
    *,
    force: bool = False,
) -> dict:
    """
    Run LLM once, persist ``ai_fit_status`` / ``ai_fit_reason`` / ``ai_fit_checked_at``.

    If already analyzed and ``force`` is False, raises ValueError (caller maps to 409).
    """
    if not llm_configured():
        raise ValueError("No LLM API keys configured — cannot run AI analysis")

    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")

    r = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    if not r:
        raise ValueError("Company row not found")

    if not force and r.ai_fit_checked_at is not None:
        raise ValueError("Already analyzed — use force to re-run")

    name = str(r.name or "").strip() or "—"
    website = str(r.website or "").strip() or "—"

    try:
        out = complete_prompt_json_object(_prompt(run, name, website))
    except Exception:
        logger.exception("analyze_run_company_fit LLM failed run_id=%s idx=%s", run_id, collect_index)
        raise ValueError("AI analysis failed — try again later")

    if not isinstance(out, dict):
        raise ValueError("Invalid AI response")

    fit = out.get("fit")
    if not isinstance(fit, bool):
        raise ValueError("Invalid AI response: fit must be boolean")

    reason_raw = out.get("reason")
    reason = str(reason_raw or "").strip()[:2000] if reason_raw is not None else ""
    if not reason:
        reason = "No reason returned."

    status: str = "correct" if fit else "incorrect"

    now = datetime.utcnow()
    r.ai_fit_status = status
    r.ai_fit_reason = reason
    r.ai_fit_checked_at = now
    db.add(r)
    db.commit()
    db.refresh(r)

    return {
        "collect_index": collect_index,
        "ai_fit_status": status,
        "ai_fit_reason": reason,
        "ai_fit_checked_at": now.isoformat() + "Z",
    }


def set_run_company_fit_manual(
    db: Session,
    run_id: int,
    collect_index: int,
    status: str,
) -> dict:
    """Manual reject-queue override: the user's verdict beats the LLM judge's.

    status: "correct" | "incorrect". The ICP gate in enrich_crm_data honors the result
    (incorrect rows get no dossier/discovery spend).
    """
    if status not in ("correct", "incorrect"):
        raise ValueError("status must be 'correct' or 'incorrect'")

    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")

    r = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    if not r:
        raise ValueError("Company row not found")

    now = datetime.utcnow()
    r.ai_fit_status = status
    r.ai_fit_reason = "Manual override"
    r.ai_fit_checked_at = now
    db.add(r)
    db.commit()
    db.refresh(r)

    return {
        "collect_index": collect_index,
        "ai_fit_status": status,
        "ai_fit_reason": "Manual override",
        "ai_fit_checked_at": now.isoformat() + "Z",
    }


def analyze_run_companies_fit_pending(
    db: Session,
    run_id: int,
    *,
    max_rows: int = 200,
    force: bool = False,
) -> dict:
    """Analyze every row with ``ai_fit_checked_at`` NULL (unless force, then all rows)."""
    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")
    if not llm_configured():
        raise ValueError("No LLM API keys configured — cannot run AI analysis")

    q = db.query(RunCompany).filter(RunCompany.run_id == run_id).order_by(RunCompany.collect_index.asc())
    if not force:
        q = q.filter(RunCompany.ai_fit_checked_at.is_(None))

    rows = q.limit(max(1, min(max_rows, 500))).all()
    results: list[dict] = []
    errors: list[str] = []

    for r in rows:
        try:
            one = analyze_run_company_fit(db, run_id, r.collect_index, force=force)
            results.append(one)
        except ValueError as e:
            msg = str(e)
            if "Already analyzed" in msg and not force:
                continue
            errors.append(f"collect_index={r.collect_index}: {msg}")
            logger.warning("analyze pending: skip idx=%s: %s", r.collect_index, msg)

    return {
        "analyzed": len(results),
        "results": results,
        "errors": errors[:50],
    }
