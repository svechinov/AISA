"""Canonical generation metadata on email_drafts: typed columns; generation_meta_json optional legacy only."""

from __future__ import annotations

from typing import Any


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def critic_taste_column_values(src: dict) -> dict[str, Any]:
    """Map the LLM taste-rubric outcome (B-077 etap 2) to its typed columns.

    ``src`` is either a validate_outbound_email() result or a generation_meta_json dict — both
    carry the same ``critic_scores``/``critic_taste_pass``/``critic_hook_grounded``/
    ``critic_canon_used``/``critic_evidence`` keys.
    """
    from app.services.email_validation_service import CRITIC_RUBRIC_KEYS

    scores = src.get("critic_scores")
    if not isinstance(scores, dict):
        scores = {}
    taste_pass = src.get("critic_taste_pass")
    hook_grounded = src.get("critic_hook_grounded")
    evidence = src.get("critic_evidence")
    return {
        "critic_taste_pass": taste_pass if isinstance(taste_pass, bool) else None,
        "critic_relevance_score": _coerce_int(scores.get(CRITIC_RUBRIC_KEYS[0])),
        "critic_specificity_score": _coerce_int(scores.get(CRITIC_RUBRIC_KEYS[1])),
        "critic_non_spam_score": _coerce_int(scores.get(CRITIC_RUBRIC_KEYS[2])),
        "critic_cta_score": _coerce_int(scores.get(CRITIC_RUBRIC_KEYS[3])),
        "critic_clarity_score": _coerce_int(scores.get(CRITIC_RUBRIC_KEYS[4])),
        "critic_hook_grounded": hook_grounded if isinstance(hook_grounded, bool) else None,
        "critic_canon_used": _opt_str(src.get("critic_canon_used")),
        "critic_evidence_json": evidence if isinstance(evidence, dict) else None,
    }


def generation_meta_dict_to_column_values(meta: dict) -> dict[str, Any]:
    """Map pipeline generation_meta_json shape to ORM column kwargs (no generation_meta_json key)."""
    r = meta.get("reasoning") if isinstance(meta.get("reasoning"), dict) else {}
    issues = meta.get("validation_issues")
    if not isinstance(issues, list):
        issues = []
    pt = meta.get("prompt_setup_text_used")
    iv = meta.get("is_valid")
    return {
        "prompt_setup_text_used": pt if isinstance(pt, str) and pt.strip() else None,
        "generation_style_mode": _opt_str(meta.get("style_mode")),
        "validation_score": _coerce_float(meta.get("validation_score")),
        "validation_issues_json": issues,
        "generation_is_valid": iv if isinstance(iv, bool) else None,
        "peer_similarity_max": _coerce_float(meta.get("peer_similarity_max")),
        "validation_retries": _coerce_int(meta.get("validation_retries")),
        "pipeline_source": _opt_str(meta.get("pipeline_source")),
        "reasoning_hook": _reasoning_str(r, "hook"),
        "reasoning_angle": _reasoning_str(r, "angle"),
        "reasoning_cta_type": _reasoning_str(r, "cta_type"),
        "reasoning_key_point": _reasoning_str(r, "key_point"),
        "reasoning_problem": _reasoning_str(r, "problem"),
        "reasoning_solution": _reasoning_str(r, "solution"),
        "matched_program_json": (
            meta.get("matched_program") if isinstance(meta.get("matched_program"), dict) else None
        ),
        # B-147: which closing-paragraph variant (0-based index) was rotated into this draft.
        "finale_variant": _coerce_int(meta.get("finale_variant")),
        **critic_taste_column_values(meta),
    }


def _reasoning_str(r: dict, key: str) -> str | None:
    v = r.get(key) if isinstance(r, dict) else None
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def apply_generation_meta_to_draft(draft: Any, meta: dict | None) -> None:
    """Persist metadata in typed columns only (no generation_meta_json blob)."""
    if meta is None:
        return
    for k, v in generation_meta_dict_to_column_values(meta).items():
        setattr(draft, k, v)


def build_generation_meta_json_from_columns(draft: Any) -> dict:
    """Rebuild the legacy generation_meta_json shape from typed columns."""
    issues = getattr(draft, "validation_issues_json", None)
    if not isinstance(issues, list):
        issues = []
    reasoning = {
        "hook": getattr(draft, "reasoning_hook", None) or "",
        "angle": getattr(draft, "reasoning_angle", None) or "",
        "cta_type": getattr(draft, "reasoning_cta_type", None) or "",
        "key_point": getattr(draft, "reasoning_key_point", None) or "",
        "problem": getattr(draft, "reasoning_problem", None) or "",
        "solution": getattr(draft, "reasoning_solution", None) or "",
    }
    vr = getattr(draft, "validation_retries", None)
    scores_cols = (
        "critic_relevance_score", "critic_specificity_score", "critic_non_spam_score",
        "critic_cta_score", "critic_clarity_score",
    )
    scores_vals = [getattr(draft, c, None) for c in scores_cols]
    critic_scores = None
    if any(v is not None for v in scores_vals):
        from app.services.email_validation_service import CRITIC_RUBRIC_KEYS

        critic_scores = dict(zip(CRITIC_RUBRIC_KEYS, scores_vals))
    return {
        "reasoning": reasoning,
        "matched_program": getattr(draft, "matched_program_json", None),
        "finale_variant": getattr(draft, "finale_variant", None),
        "style_mode": getattr(draft, "generation_style_mode", None) or "",
        "validation_score": getattr(draft, "validation_score", None),
        "validation_issues": issues,
        "is_valid": getattr(draft, "generation_is_valid", None),
        "peer_similarity_max": getattr(draft, "peer_similarity_max", None),
        "validation_retries": int(vr) if vr is not None else 0,
        "pipeline_source": getattr(draft, "pipeline_source", None) or "",
        "prompt_setup_text_used": getattr(draft, "prompt_setup_text_used", None),
        "critic_taste_pass": getattr(draft, "critic_taste_pass", None),
        "critic_scores": critic_scores,
        "critic_hook_grounded": getattr(draft, "critic_hook_grounded", None),
        "critic_canon_used": getattr(draft, "critic_canon_used", None),
        "critic_evidence": getattr(draft, "critic_evidence_json", None),
    }


def effective_generation_meta_json(draft: Any) -> dict | None:
    """API payload: rebuild from columns when pipeline_source is set, else legacy generation_meta_json."""
    if getattr(draft, "pipeline_source", None) is not None:
        return build_generation_meta_json_from_columns(draft)
    raw = getattr(draft, "generation_meta_json", None)
    if isinstance(raw, dict) and raw:
        return raw
    return None


def effective_generation_meta_json_for_list(draft: Any) -> dict | None:
    """GET /email-drafts/run list rows: omit ``prompt_setup_text_used`` (duplicates top-level field)
    and ``critic_canon_used``/``critic_evidence`` (heavy/duplicative — not needed in list payloads)."""
    meta = effective_generation_meta_json(draft)
    if not isinstance(meta, dict) or not meta:
        return None
    _excluded = ("prompt_setup_text_used", "critic_canon_used", "critic_evidence")
    slim = {k: v for k, v in meta.items() if k not in _excluded}
    return slim if slim else None


def effective_prompt_setup_text_used(draft: Any) -> str | None:
    col = getattr(draft, "prompt_setup_text_used", None)
    if isinstance(col, str) and col.strip():
        return col.strip()
    meta = effective_generation_meta_json(draft)
    if not isinstance(meta, dict):
        return None
    v = meta.get("prompt_setup_text_used")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None
