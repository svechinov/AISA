"""Fixed email closing paragraphs by recipient geo-segment (B-063, ru-email-canon.md §2.2,
approved by Алексей 2026-07-15; iT_Party naming + no-Malindi verbatim variants approved 2026-07-16).

The closing paragraph — self-intro (co-founder) + meeting offer + one CTA question — is a
deliberately fixed template per segment: "if I were sending these by hand, I'd use a template"
(Алексей, 2026-07-15). generate_email_draft (outreach_email_pipeline.py) injects the selected
segment/language block into the prompt with a "use verbatim" instruction; only synonym-level
leeway is allowed (happy<->glad, quick<->short) — structure and meaning must not change.
resolve_geo_segment (geo_segment_service.py) picks the segment + malindi/ex_cis flags.

B-071 (data-driven personas, decision 8/9): the templates are no longer module constants — they
live in persona.finales_json (app.services.persona_service.ALEXEY_FINALES_JSON holds the alexey
persona's byte-identical migration of the old FINALE_TEMPLATES/SEGMENT_NAMES). get_finale_text and
finale_instruction_block below are generic resolvers over any persona's finales_json; only the data
is Cyprus/alexey-specific now, not the code.

Malindi venue naming (fact correction, 2026-07-16): the Wednesday meetup at Malindi is officially
Cyprus_iT Networking, colloquially "iT_Party" (that exact casing/underscore) — an expat gathering
on Cyprus, mostly IT crowd. The prior placeholder phrasing for this venue is retired. The ex-CIS
filter and segment rules are unchanged; only the venue's name in the fixed text changed. For
non-ex-CIS recipients (malindi=False) segments 2/3 use their own dedicated no-Malindi verbatim
variant (not an edit instruction) — segment 4 has no in-person option without Malindi and
collapses into segment 3's no-Malindi variant (decision 3, unchanged).

Segment 5 (recipient not on Cyprus) has two EN variants — ex-CIS gets "here or on Telegram",
everyone else gets "over email" — per canon. Segments 1-4 are Cyprus-only.

B-147 (rotation, decision 20.07): a variant slot's value is no longer necessarily a single string —
it can be a LIST of verbatim options (A/B/C...), rotated at random per generation. A bare string is
legacy data (one option) and is treated as a 1-item list — coerce_variant_list below is the single
place that normalizes this, used both here and by email_validation_service's fixed-block matcher
(the critic must recognize ANY of a segment's variants as the known fixed block, not just one).

B-158 (2026-07-21, root-cause fix): asking the LLM to reproduce the closing paragraph "verbatim"
was not reliable — it occasionally rewrote it in its own words (e.g. to dodge HARD RULE 15's em
dash ban, since the old variant A text contains one). The live pipeline
(outreach_email_pipeline.generate_email_draft) no longer asks the model to write a closing
paragraph at all; it appends get_finale_text(...)'s result in code after generation, so byte-
exactness is guaranteed by construction, not by LLM compliance. finale_instruction_block below is
kept only for its historical prompt-instruction shape (the byte-identity harness in
test_persona_finale_regression.py still exercises it) — the live pipeline no longer calls it.
"""

from __future__ import annotations

import random
from typing import Any


def coerce_variant_list(value: Any) -> list[str]:
    """A variant slot's value is a list of verbatim options (B-147) or legacy bare string (one
    option) — normalize to a list either way. Falsy/malformed values become an empty list."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v]
    if isinstance(value, str) and value:
        return [value]
    return []


def effective_segment_for_malindi(persona: Any, segment: str, malindi: bool) -> str:
    """Segment 4 without Malindi collapses into segment 3's no-Malindi text (decision 3, B-071) —
    shared by finale_instruction_block and pick_finale_variant_index (B-147) so the variant index
    picked ahead of time lines up with the options finale_instruction_block resolves."""
    collapse = ((persona.geo_map_json or {}).get("modifiers") or {}).get("segment4_collapse") or {}
    if not malindi and segment == collapse.get("from"):
        return collapse.get("to_no_malindi_of", segment)
    return segment


def _resolve_variant_list(
    segments_map: dict[str, Any],
    fallbacks: dict[str, str],
    segment: str,
    lang_key: str,
    ex_cis: bool,
    malindi: bool,
    _depth: int = 0,
) -> list[str]:
    """Pick the most specific variant-option-list present for (segment, lang_key, ex_cis, malindi),
    else follow the segment's explicit fallback chain (decision 10, B-071) — no silent substitution."""
    variants = (segments_map.get(segment) or {}).get("variants") or {}

    candidates: list[str] = []
    if ex_cis:
        candidates.append(f"{lang_key}_ex_cis")
    if not malindi:
        candidates.append(f"{lang_key}_no_malindi")
    candidates.append(lang_key)

    for key in candidates:
        options = coerce_variant_list(variants.get(key))
        if options:
            return options

    if _depth > 5:  # guard against a malformed/cyclic fallback chain
        return []
    fallback_target = fallbacks.get(f"{segment}.{lang_key}")
    if not fallback_target:
        return []
    target_segment, _, target_lang = fallback_target.partition(".")
    return _resolve_variant_list(
        segments_map, fallbacks, target_segment, target_lang, ex_cis, malindi, _depth + 1
    )


def get_finale_variants(
    persona: Any, segment: str, language: str, ex_cis: bool = False, malindi: bool = True
) -> list[str]:
    """Segment key + language ('Russian' or else English) + ex_cis + malindi -> ALL verbatim
    closing-paragraph options from persona.finales_json (B-147: order preserved, index 0 = variant
    A, 1 = variant B, ...). Legacy single-string data resolves to a 1-item list."""
    finales = persona.finales_json or {}
    segments_map: dict[str, Any] = finales.get("segments") or {}
    fallbacks: dict[str, str] = finales.get("fallbacks") or {}

    if segment not in segments_map:
        segment = (persona.geo_map_json or {}).get("default_segment", segment)

    lang_key = "ru" if (language or "").strip().lower() == "russian" else "en"

    options = _resolve_variant_list(segments_map, fallbacks, segment, lang_key, ex_cis, malindi)
    if options:
        return options

    variants = (segments_map.get(segment) or {}).get("variants") or {}
    return coerce_variant_list(variants.get(lang_key)) or coerce_variant_list(variants.get("en"))


def pick_finale_variant_index(
    persona: Any,
    segment: str,
    language: str,
    ex_cis: bool,
    malindi: bool,
    rng: Any = None,
) -> int:
    """Choose a variant index for (segment, language, ex_cis, malindi) — B-147 rotation. Applies
    the same segment-4-collapse as finale_instruction_block so the index lines up with the options
    that function will actually resolve. rng defaults to the `random` module; pass a seeded
    random.Random for deterministic tests. A single-option segment always returns 0."""
    effective_segment = effective_segment_for_malindi(persona, segment, malindi)
    options = get_finale_variants(persona, effective_segment, language, ex_cis, malindi)
    if not options:
        return 0
    picker = rng or random
    return picker.randrange(len(options))


def get_finale_text(
    persona: Any,
    segment: str,
    language: str,
    ex_cis: bool = False,
    malindi: bool = True,
    *,
    variant_index: int | None = None,
) -> str:
    """One verbatim closing-paragraph text for (segment, language, ex_cis, malindi).
    variant_index selects which option (B-147 rotation, e.g. from pick_finale_variant_index);
    None (default) picks uniformly at random — a segment with a single legacy option always
    resolves to that option regardless, so old callers keep their old, deterministic behavior."""
    options = get_finale_variants(persona, segment, language, ex_cis, malindi)
    if not options:
        return ""
    if variant_index is None:
        return random.choice(options)
    return options[variant_index % len(options)]


def finale_instruction_block(
    persona: Any,
    segment: str,
    language: str,
    malindi: bool,
    ex_cis: bool,
    *,
    variant_index: int | None = None,
) -> str:
    """Build the prompt block that pins the closing paragraph verbatim (decisions 1 & 4, B-063).

    A segment without Malindi that has no in-person option of its own left collapses into another
    segment's no-Malindi verbatim variant, per persona.geo_map_json.modifiers.segment4_collapse
    (decision 3, data-driven under B-071) — not an edit instruction, a distinct fixed text.

    variant_index (B-147): which of the resolved segment's variants to use — pass the value from
    pick_finale_variant_index() so the same generation attempt's retries (and the persisted
    email_drafts.finale_variant) all agree on one choice. None picks at random.
    """
    effective_segment = effective_segment_for_malindi(persona, segment, malindi)

    text = get_finale_text(
        persona, effective_segment, language, ex_cis, malindi, variant_index=variant_index
    )

    segments_map = (persona.finales_json or {}).get("segments") or {}
    seg_meta = segments_map.get(effective_segment) or {}
    ordinal = seg_meta.get("prompt_ordinal", effective_segment)
    label = seg_meta.get("label", "")

    return (
        f"CLOSING PARAGRAPH (segment {ordinal}/{label}) — USE THIS VERBATIM as the "
        "email's final paragraph (self-intro + meeting offer + one closing CTA question). Only "
        "synonym-level leeway is allowed (e.g. 'happy to' <-> 'glad to', 'quick' <-> 'short'); "
        "do not restructure the sentence or change its meaning:\n"
        f'"{text}"'
    )
