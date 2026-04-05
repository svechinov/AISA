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
    }
    vr = getattr(draft, "validation_retries", None)
    return {
        "reasoning": reasoning,
        "style_mode": getattr(draft, "generation_style_mode", None) or "",
        "validation_score": getattr(draft, "validation_score", None),
        "validation_issues": issues,
        "is_valid": getattr(draft, "generation_is_valid", None),
        "peer_similarity_max": getattr(draft, "peer_similarity_max", None),
        "validation_retries": int(vr) if vr is not None else 0,
        "pipeline_source": getattr(draft, "pipeline_source", None) or "",
        "prompt_setup_text_used": getattr(draft, "prompt_setup_text_used", None),
    }


def effective_generation_meta_json(draft: Any) -> dict | None:
    """API payload: rebuild from columns when pipeline_source is set, else legacy generation_meta_json."""
    if getattr(draft, "pipeline_source", None) is not None:
        return build_generation_meta_json_from_columns(draft)
    raw = getattr(draft, "generation_meta_json", None)
    if isinstance(raw, dict) and raw:
        return raw
    return None


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
