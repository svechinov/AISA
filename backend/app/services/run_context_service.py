"""Run-level outreach brief: nested context, master prompt, per-step LLM task wording."""

from __future__ import annotations

from typing import Any

_CONTEXT_KEYS = ("offer", "target_entities", "target_roles", "goal", "tone", "notes")


def coalesce_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _empty_inner_context() -> dict[str, str]:
    return {k: "" for k in _CONTEXT_KEYS}


def _line_label_and_rest(line: str) -> tuple[str | None, str]:
    """Match 'Offer:', 'Target:', 'Target entities:', etc. (case-insensitive)."""
    s = line.strip()
    if not s:
        return None, ""
    lower = s.lower()
    pairs: list[tuple[str, str]] = [
        ("offer:", "offer"),
        ("target entities:", "target_entities"),
        ("target:", "target_entities"),
        ("target roles:", "target_roles"),
        ("roles:", "target_roles"),
        ("role:", "target_roles"),
        ("goal:", "goal"),
        ("tone:", "tone"),
        ("notes:", "notes"),
    ]
    for prefix, key in pairs:
        if lower.startswith(prefix):
            rest = s[len(prefix) :].lstrip()
            return key, rest
    return None, s


def parse_outreach_brief_text(raw: str) -> dict[str, str]:
    """
    Parse a labeled textarea, e.g.:

    Offer: ...
    Target: ...
    Roles: ...
    Goal: ...
    Tone: ...
    Notes: ...
    """
    result = _empty_inner_context()
    text = coalesce_str(raw)
    if not text:
        return result

    current_key: str | None = None
    chunks: list[str] = []

    def flush():
        nonlocal chunks, current_key
        if current_key is not None:
            result[current_key] = "\n".join(chunks).strip()
        chunks = []

    for line in text.splitlines():
        lk, rest = _line_label_and_rest(line)
        if lk is not None:
            flush()
            current_key = lk
            if rest:
                chunks.append(rest)
        elif current_key is not None:
            chunks.append(line)
        elif line.strip():
            if not result["notes"]:
                result["notes"] = line.strip()
            else:
                result["notes"] = result["notes"] + "\n" + line

    flush()
    return result


def wrap_context(inner: dict[str, str]) -> dict:
    """DB shape: {\"context\": {...}}."""
    return {"context": {k: coalesce_str(inner.get(k, "")) for k in _CONTEXT_KEYS}}


def merge_inner_from_legacy_fields(
    inner: dict[str, str],
    *,
    product: str,
    target_entities: str,
    target_roles: str,
    outreach_goal: str,
    tone: str,
    extra_context: str,
) -> dict[str, str]:
    """Fill empty inner fields from API legacy flat fields."""
    legacy = {
        "offer": coalesce_str(product),
        "target_entities": coalesce_str(target_entities),
        "target_roles": coalesce_str(target_roles),
        "goal": coalesce_str(outreach_goal),
        "tone": coalesce_str(tone) or "Professional",
        "notes": coalesce_str(extra_context),
    }
    out = dict(inner)
    for k in _CONTEXT_KEYS:
        if not out.get(k):
            out[k] = legacy[k]
    if not out.get("tone"):
        out["tone"] = "Professional"
    return out


def get_effective_context(run) -> dict[str, str]:
    """Normalized inner context (offer, target_entities, …), including legacy rows."""
    raw_outer = dict(run.context_json or {})
    inner: dict[str, Any] = {}

    ctx_nested = raw_outer.get("context")
    if isinstance(ctx_nested, dict):
        inner = {k: coalesce_str(ctx_nested.get(k, "")) for k in _CONTEXT_KEYS}

    if not inner or not any(coalesce_str(inner.get(k)) for k in _CONTEXT_KEYS):
        inner = {
            "offer": coalesce_str(raw_outer.get("offer") or raw_outer.get("product")),
            "target_entities": coalesce_str(raw_outer.get("target_entities")),
            "target_roles": coalesce_str(raw_outer.get("target_roles")),
            "goal": coalesce_str(raw_outer.get("goal") or raw_outer.get("outreach_goal")),
            "tone": coalesce_str(raw_outer.get("tone")) or "Professional",
            "notes": coalesce_str(raw_outer.get("notes") or raw_outer.get("extra_context")),
        }

    if not inner.get("goal") and not inner.get("offer"):
        legacy_goal = coalesce_str((run.input_json or {}).get("goal"))
        if legacy_goal:
            inner["goal"] = legacy_goal

    if not inner.get("notes"):
        inner["notes"] = coalesce_str(run.notes)

    return {
        "offer": coalesce_str(inner.get("offer")),
        "target_entities": coalesce_str(inner.get("target_entities")),
        "target_roles": coalesce_str(inner.get("target_roles")),
        "goal": coalesce_str(inner.get("goal")),
        "tone": coalesce_str(inner.get("tone")) or "Professional",
        "notes": coalesce_str(inner.get("notes")),
    }


def build_master_prompt_text(ctx: dict[str, str]) -> str:
    """Single universal master prompt for search + email steps."""
    return (
        "You are an expert in B2B outreach.\n\n"
        "Context:\n"
        f"Offer: {ctx['offer'] or '—'}\n"
        f"Goal: {ctx['goal'] or '—'}\n"
        f"Target entities: {ctx['target_entities'] or '—'}\n"
        f"Target roles: {ctx['target_roles'] or '—'}\n"
        f"Tone: {ctx['tone']}\n"
        f"Additional context: {ctx['notes'] or '—'}\n\n"
        "Your tasks will be based ONLY on this context.\n"
        "Do not assume industry (like VOD) unless explicitly stated."
    ).strip()


def build_pack_step_zero_input(run) -> dict:
    ctx = get_effective_context(run)
    mp = coalesce_str(getattr(run, "master_prompt", None))
    return {
        "run_context": {"context": ctx},
        "master_prompt": mp,
        "segment": coalesce_str(run.segment),
    }


def build_collect_companies_input_for_round(
    run,
    companies: list[dict],
    round_idx: int,
) -> dict:
    """Input for collect_companies; later rounds include prior companies so the model expands the list."""
    base = build_pack_step_zero_input(run)
    if companies:
        base["companies"] = companies
        base["expansion_round"] = round_idx + 1
        base["expansion_note"] = (
            f"Additional pass {round_idx + 1}: {len(companies)} companies already listed in INPUT DATA. "
            "Return NEW companies only (no duplicates); keep aligning with the goal."
        )
    return base


def build_collect_companies_task(run) -> str:
    mp = coalesce_str(getattr(run, "master_prompt", None))
    return (
        f"{mp}\n\n"
        "Task:\n"
        "Find 20 relevant companies or organizations that match the target entities.\n\n"
        "Return:\n"
        "- company name\n"
        "- website\n\n"
        "Be precise and relevant to the goal."
    )


def build_find_contacts_task(run) -> str:
    mp = coalesce_str(getattr(run, "master_prompt", None))
    ctx = get_effective_context(run)
    roles = ctx["target_roles"] or "—"
    return (
        f"{mp}\n\n"
        "Task:\n"
        "For each company, identify people with relevant roles.\n\n"
        "Target roles:\n"
        f"{roles}\n\n"
        "Return:\n"
        "- full name\n"
        "- role\n"
        "- email (if possible)\n\n"
        "Focus on decision-makers relevant to the goal."
    )
