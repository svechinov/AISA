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
    """Match 'Offer:', 'Target:', '**Goal:**', 'Professional Notes:', etc. (case-insensitive)."""
    s = line.strip()
    if not s:
        return None, ""
    # Markdown-wrapped labels break prefix match; strip * for detection only.
    s = s.replace("*", "").strip()
    if not s:
        return None, ""
    lower = s.lower()
    pairs: list[tuple[str, str]] = [
        ("target entities:", "target_entities"),
        ("professional notes:", "notes"),
        ("target roles:", "target_roles"),
        ("offer:", "offer"),
        ("target:", "target_entities"),
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
    oc = getattr(run, "outreach_context", None)
    if oc is not None:
        inner_oc = {
            "offer": coalesce_str(oc.offer),
            "target_entities": coalesce_str(oc.target_entities),
            "target_roles": coalesce_str(oc.target_roles),
            "goal": coalesce_str(oc.goal),
            "tone": coalesce_str(oc.tone) or "Professional",
            "notes": coalesce_str(oc.notes),
        }
        if any(coalesce_str(inner_oc.get(k)) for k in _CONTEXT_KEYS):
            inner = inner_oc
        else:
            inner = {}
    else:
        inner = {}

    raw_outer = dict(run.context_json or {})
    if not inner or not any(coalesce_str(inner.get(k)) for k in _CONTEXT_KEYS):
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
        legacy_goal = coalesce_str(getattr(run, "input_goal", None))
        if not legacy_goal:
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


def get_prompt_setup_text(run) -> str:
    """Labeled outreach brief — only ``run_setups.prompt_setup_text`` (migrated from context_json on startup)."""
    rs = getattr(run, "run_setup", None)
    if rs is not None and rs.prompt_setup_text is not None:
        return (rs.prompt_setup_text or "").strip()
    return ""


def get_sender_signature_html(run) -> str | None:
    """HTML signature — only ``run_setups.sender_signature_html`` (migrated from runs.sender_signature_html on startup)."""
    rs = getattr(run, "run_setup", None)
    if rs is not None and rs.sender_signature_html is not None:
        return rs.sender_signature_html
    return None


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
    *,
    continuation: bool = False,
) -> dict:
    """Input for collect_companies (no embedded company list — worker loads prior rows from run_companies)."""
    base = build_pack_step_zero_input(run)
    base["continuation"] = continuation
    if companies:
        base["expansion_round"] = round_idx + 1
        note = (
            f"Additional pass {round_idx + 1}: {len(companies)} companies already listed in INPUT DATA. "
            "Return NEW companies only (no duplicates); keep aligning with the goal."
        )
        if continuation:
            note += (
                ' This pass is "Continue outreach" — prioritize growing the list: new regions, '
                "adjacent categories, indie or B2B brands, not repeats of names already in INPUT DATA."
            )
            # Rotate angles so the model does not keep suggesting the same 20 brands every pass.
            themes = [
                "This round: prioritize companies headquartered or primarily selling in **different US states/regions** "
                "than those already implied by INPUT DATA (avoid repeating the same metro clusters).",
                "This round: prioritize **indie brands**, **promotional product vendors**, **print shops**, "
                "and **B2B distributors** that may not be household names.",
                "This round: prioritize **sporting goods**, **outdoor**, **museum gift shops**, **tourism retail**, "
                "and **event merchandising** channels.",
                "This round: prioritize **e-commerce native brands**, **Etsy-scale makers**, **wholesale marketplaces**, "
                "and **private-label** programs.",
            ]
            base["diversity_guidance"] = themes[round_idx % len(themes)]
        base["expansion_note"] = note
    return base


def build_collect_companies_task(run, *, continuation: bool = False) -> str:
    mp = coalesce_str(getattr(run, "master_prompt", None))
    n = "35–50" if continuation else "20"
    return (
        f"{mp}\n\n"
        "Task:\n"
        f"List up to {n} relevant real-world companies or organizations that match the target entities.\n\n"
        "Hard requirements:\n"
        "- Only include organizations that plausibly exist: use names and domains you could verify on the open web "
        "(official site, news, registries). Do not invent brands, cute fake names, or placeholder companies.\n"
        "- Website must be the organization’s real primary domain (https://…). No example.com, localhost, or "
        "made-up TLDs. If you are not confident a company is real, omit it rather than guessing.\n"
        "- Prefer well-known or easy-to-check businesses over obscure names you are unsure about.\n\n"
        "Return:\n"
        "- company name (as commonly used publicly)\n"
        "- website (canonical URL)\n\n"
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
