"""LLM judges whether a collected company fits the run's outreach campaign (one row at a time)."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.excluded_company import EXCLUDE_REASON_OFF_SEGMENT
from app.models.run_company import RunCompany
from app.repositories.excluded_company_repo import add_excluded_company
from app.repositories.run_repo import get_run
from app.services.llm_gateway import complete_prompt_json_object, llm_configured
from app.services.run_context_service import build_master_prompt_text, coalesce_str, get_effective_context

logger = logging.getLogger(__name__)

# Fork-transition Phase 1, Task 6: the worked example here ("a training/consulting provider when
# we sell training") assumed AlexStaff's offer is never itself training/consulting. A campaign
# whose OWN offer IS training/consulting-adjacent (NODA12 trek A: selling a facilitation tool TO
# training/consulting companies) could have every real buyer misread as a same-offer competitor by
# an LLM taking the example literally. Overridable per run via run_setups.fit_exclusion_rules_text;
# empty/unset falls back to this text verbatim (byte-identical to pre-Task-6 behavior).
DEFAULT_FIT_EXCLUSION_RULES = (
    "Mark **incorrect** ONLY when:\n"
    "- the company is a COMPETITOR / provider of the SAME offer (e.g. a training/consulting provider "
    "when we sell training — they are peers, not buyers); or\n"
    "- it is not a real buyer organization (an individual, a job board, an event page, a government "
    "procurement agency that purchases on behalf of others rather than for itself); or\n"
    "- it clearly cannot have the need the offer addresses per the campaign brief.\n"
    "Otherwise mark **correct**."
)


def _fit_exclusion_rules_for(run) -> str:
    run_setup = getattr(run, "run_setup", None)
    text = (getattr(run_setup, "fit_exclusion_rules_text", None) or "").strip()
    return text or DEFAULT_FIT_EXCLUSION_RULES


def _prompt(run, company_name: str, company_website: str) -> str:
    from app.services.run_context_service import get_prompt_setup_text

    ctx = get_effective_context(run)
    brief = build_master_prompt_text(ctx)
    mp = coalesce_str(getattr(run, "master_prompt", None))
    block = f"{mp}\n\n---\n{brief}" if mp else brief
    offer = get_prompt_setup_text(run)
    offer_block = f"What we SELL (our offer/persona):\n{offer}\n\n" if offer else ""
    return (
        "You decide whether a REAL company is a plausible PROSPECT (a potential BUYER) for THIS "
        "outreach campaign — i.e. a company we would sell our offer TO.\n\n"
        "CRITICAL framing:\n"
        "- The prospect's OWN industry is almost never disqualifying. A retailer, a bank, a factory, "
        "an agro holding can all be valid prospects for e.g. a training/consulting offer — what matters "
        "is whether they plausibly have the NEED or pain the offer addresses (large workforce, hiring, "
        "scaling, management/sales challenges, etc.).\n"
        "- Do NOT require the company to be in the same industry as the offer. Selling training to a "
        "retailer is normal; the retailer is NOT 'off-target' just because it is not a training company.\n\n"
        f"{_fit_exclusion_rules_for(run)}\n\n"
        "Return ONLY valid JSON (no markdown) with this exact shape:\n"
        '{"fit": true or false, "reason": "one short English sentence"}\n\n'
        f"Company name: {company_name}\n"
        f"Website: {company_website or '—'}\n\n"
        f"{offer_block}"
        "Who we target (campaign brief):\n"
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
    *,
    exclude_cross_run: bool = True,
    exclude_reason: str = EXCLUDE_REASON_OFF_SEGMENT,
    exclude_note: str | None = None,
) -> dict:
    """Manual reject-queue override: the user's verdict beats the LLM judge's.

    status: "correct" | "incorrect". The ICP gate in enrich_crm_data honors the result
    (incorrect rows get no dossier/discovery spend).

    B-264: a MANUAL "incorrect" is also written to the cross-run exclusion registry, so the next
    Apollo sweep with the same filters does not collect this company again (`exclude_cross_run=False`
    keeps the verdict inside the run — for a company that is off-segment only for THIS campaign).
    The LLM judge's own verdict is never promoted this way: it is wrong often enough that a
    permanent, cross-run ban must stay a human decision.
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

    excluded = None
    if status == "incorrect" and exclude_cross_run:
        excluded = add_excluded_company(
            db,
            name=r.name,
            website=r.website,
            reason=exclude_reason,
            note=exclude_note or f"Не наш сегмент (ручной вердикт, ран {run_id})",
            source_run_id=run_id,
        )

    return {
        "collect_index": collect_index,
        "ai_fit_status": status,
        "ai_fit_reason": "Manual override",
        "ai_fit_checked_at": now.isoformat() + "Z",
        "excluded_company_id": getattr(excluded, "id", None),
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
