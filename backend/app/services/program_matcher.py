"""Program matcher (Feature 1): pick the catalog training program that best fits the company pain.

Runs between reasoning and draft in outreach_email_pipeline. Input: the reasoning `problem` slot
plus evidence (dossier / person_osint). Output: the matched program with a tailored solution text
for the `solution` slot, or None when the catalog is empty or nothing fits (pipeline then keeps
the generic prompt_setup_text offer — zero behavior change until the catalog is filled).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.models.training_program import TrainingProgram
from app.services.llm_gateway import complete_prompt_json_object

logger = logging.getLogger(__name__)

MATCH_SCHEMA = {
    "program_id": "integer or null",
    "fit_score": "integer 0-100",
    "solution_text": "string",
    "rationale": "string",
}


def _min_fit() -> int:
    """Matches below this fit_score are discarded (fall back to generic offer)."""
    raw = os.environ.get("PROGRAM_MATCH_MIN_FIT", "").strip()
    try:
        return int(raw) if raw else 55
    except ValueError:
        return 55


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

    programs = (
        db.query(TrainingProgram)
        .filter(TrainingProgram.status == "active")
        .order_by(TrainingProgram.id.asc())
        .all()
    )
    if not programs:
        return None

    import json as _json

    prompt = (
        f"ALWAYS WRITE solution_text AND rationale IN {language}.\n\n"
        "You are matching a corporate training program to a prospect's confirmed pain.\n\n"
        f"PROSPECT PAIN (from evidence-grounded reasoning):\n{problem}\n\n"
        + (f"COMPANY DOSSIER (excerpt):\n{dossier[:2000]}\n\n" if dossier else "")
        + (
            f"PERSON OSINT (decision maker):\n{_json.dumps(person_osint, ensure_ascii=False)[:1500]}\n\n"
            if person_osint
            else ""
        )
        + "PROGRAM CATALOG:\n"
        f"{_json.dumps(_catalog_for_prompt(programs), ensure_ascii=False)}\n\n"
        "TASK:\n"
        "1. Pick the ONE program whose target_pains best match the prospect pain. "
        "If none is a genuinely good fit, return program_id=null (do NOT force a weak match).\n"
        "2. fit_score: honest 0-100 fit (90+ exact pain match; <55 weak/generic).\n"
        "3. solution_text: 2-3 sentences for the email's solution slot — name the program "
        "explicitly, tie it to THIS prospect's pain, and weave in 1-2 of its bullets. "
        "Concrete and specific, no generic consulting language.\n"
        "4. rationale: one sentence — why this program fits this pain (internal, not for the email).\n\n"
        "Return STRICT JSON: "
        '{"program_id": <int|null>, "fit_score": <int>, "solution_text": "...", "rationale": "..."}'
    )

    try:
        out = complete_prompt_json_object(prompt)
    except Exception as e:
        logger.warning(f"Program matcher LLM call failed (keeping generic offer): {e}")
        return None
    if not isinstance(out, dict):
        return None

    pid = out.get("program_id")
    try:
        fit = int(out.get("fit_score") or 0)
    except (TypeError, ValueError):
        fit = 0
    solution_text = (out.get("solution_text") or "").strip()

    if pid is None or not solution_text:
        logger.info("Program matcher: no fitting program for this pain")
        return None
    if fit < _min_fit():
        logger.info(f"Program matcher: best fit {fit} below threshold {_min_fit()} — generic offer kept")
        return None

    by_id = {p.id: p for p in programs}
    program = by_id.get(pid if isinstance(pid, int) else None)
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
