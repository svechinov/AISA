"""Program matcher (Feature 1): pick the catalog training program that best fits the company pain.

Runs between reasoning and draft in outreach_email_pipeline. Input: the reasoning `problem` slot
plus evidence (dossier / person_osint). Output: the matched program with a tailored solution text
for the `solution` slot, or None when the catalog is empty or nothing fits (pipeline then keeps
the generic prompt_setup_text offer — zero behavior change until the catalog is filled).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.training_program import TrainingProgram
from app.services.llm_gateway import complete_prompt_json_object
from app.services.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

MATCH_SCHEMA = {
    "program_id": "integer id from the catalog, or null when nothing genuinely fits",
    "fit_score": "integer 0-100 (90+ exact pain match; below 55 weak/generic)",
    "solution_text": "string: 2-3 sentences for the email solution slot",
    "rationale": "string: one internal sentence why this program fits",
}


def _min_fit() -> int:
    """Matches below this fit_score are discarded (fall back to generic offer)."""
    from app.utils.env_utils import env_int

    return env_int("PROGRAM_MATCH_MIN_FIT", 55)


def _coerce_int(v: Any) -> int | None:
    """LLMs regularly string-type numbers ('3', '87.5') — never let that kill a match."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _catalog_for_prompt(programs: list[TrainingProgram]) -> list[dict[str, Any]]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": (p.description or "")[:600],
            "target_pains": p.target_pains or [],
            "audience": p.audience or "",
            "format": p.format or "",
            "bullets": p.bullets or [],
        }
        for p in programs
    ]


def match_program(
    db: Session,
    *,
    problem: str,
    dossier: str = "",
    person_osint: Any = None,
    language: str = "Russian",
) -> dict[str, Any] | None:
    """One LLM call: choose the best-fitting active program for this pain, or none.

    Returns {"program_id", "name", "asset_id", "format", "bullets", "solution_text",
    "rationale", "fit_score"} or None. Never raises — a matcher failure must not break
    email generation (callers treat None as "keep generic offer").
    """
    problem = (problem or "").strip()
    if not problem:
        return None

    try:
        programs = (
            db.query(TrainingProgram)
            .filter(TrainingProgram.status == "active")
            .order_by(TrainingProgram.id.asc())
            .all()
        )
        if not programs:
            return None

        task = (
            f"ALWAYS WRITE solution_text AND rationale IN {language}.\n\n"
            "You are matching a corporate training program to a prospect's confirmed pain.\n"
            "1. Pick the ONE catalog program whose target_pains best match the prospect pain. "
            "If none is a genuinely good fit, return program_id=null (do NOT force a weak match).\n"
            "2. fit_score: honest 0-100 fit (90+ exact pain match; <55 weak/generic).\n"
            "3. solution_text: 2-3 sentences for the email's solution slot — name the program "
            "explicitly, tie it to THIS prospect's pain, and weave in 1-2 of its bullets. "
            "Concrete and specific, no generic consulting language.\n"
            "4. rationale: one sentence — why this program fits this pain (internal, not for the email)."
        )
        data: dict[str, Any] = {
            "prospect_pain": problem,
            "program_catalog": _catalog_for_prompt(programs),
        }
        if dossier:
            data["company_dossier_excerpt"] = dossier[:2000]
        if person_osint:
            data["person_osint"] = person_osint

        prompt = build_prompt(task=task, data=data, rules=[], output_schema=MATCH_SCHEMA)
        out = complete_prompt_json_object(prompt)
    except Exception as e:
        logger.warning(f"Program matcher failed (keeping generic offer): {e}")
        return None
    if not isinstance(out, dict):
        return None

    pid = _coerce_int(out.get("program_id"))
    fit = _coerce_int(out.get("fit_score")) or 0
    solution_text = (out.get("solution_text") or "").strip()

    if pid is None or not solution_text:
        logger.info("Program matcher: no fitting program for this pain")
        return None
    min_fit = _min_fit()
    if fit < min_fit:
        logger.info(f"Program matcher: best fit {fit} below threshold {min_fit} — generic offer kept")
        return None

    program = next((p for p in programs if p.id == pid), None)
    if not program:
        logger.warning(f"Program matcher returned unknown program_id={pid!r} — ignored")
        return None

    logger.info(f"Program matcher: matched '{program.name}' (fit={fit})")
    return {
        "program_id": program.id,
        "name": program.name,
        "asset_id": program.asset_id,
        "format": program.format or "",
        "bullets": program.bullets or [],
        "solution_text": solution_text,
        "rationale": (out.get("rationale") or "").strip(),
        "fit_score": fit,
    }
