"""B-147: finale variants as a LIST per segment, rotated at random per generation, with the
chosen index persisted to email_drafts.finale_variant and the critic's fixed-block matcher
recognizing ANY variant (not just the first) as a known, deliberately-shared closing paragraph.

Byte-identity requirement (per B-071's original regression harness, same spirit): each variant's
text must come back byte-for-byte unchanged, whichever index is requested — this file does not
duplicate test_persona_finale_regression.py's legacy-vs-new harness (that one stays untouched,
still single-variant, still passing unmodified — B-147's optional variant_index kwarg is fully
backward compatible), it adds coverage for the NEW multi-variant behavior specifically.
"""

from __future__ import annotations

import importlib
import pkgutil
import random

# Register every model with Base BEFORE any ORM instance (e.g. Persona(...) below) is constructed
# — SQLAlchemy configures ALL mappers in the shared registry on first use, and a relationship
# (e.g. Contact -> ContactPersonalization) fails to resolve if its target class was never imported
# yet. Same pattern as test_persona_finale_regression.py's guard.
import app.models as _models_pkg

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

from app.models.persona import Persona  # noqa: E402
from app.services.email_finale_templates import (  # noqa: E402
    coerce_variant_list,
    finale_instruction_block,
    get_finale_text,
    get_finale_variants,
    pick_finale_variant_index,
)

_VARIANT_A = "Variant A: the current finale, verbatim."
_VARIANT_B = 'Would you have 15 minutes for a call? Or, if you happen to be in Limassol or Paphos, a coffee, or Malindi on a Wednesday.'
_VARIANT_C = "I co-founded the agency and I'm based on Cyprus. If you happen to be in Limassol or Paphos, coffee is on me. Or we could meet at the Malindi IT party any Wednesday. Or would a quick 15-minute call be easier?"


def _multi_variant_persona(slug: str) -> Persona:
    """A minimal persona with 3 rotated variants on one segment ("paphos"/"en"), matching the
    A/B/C shape B-147 will seed onto the real alexey persona's Cyprus segment."""
    return Persona(
        slug=slug,
        display_name="B147 Test",
        geo_map_json={"default_segment": "paphos"},
        finales_json={
            "segments": {
                "paphos": {
                    "prompt_ordinal": 1,
                    "label": "Paphos",
                    "variants": {"en": [_VARIANT_A, _VARIANT_B, _VARIANT_C]},
                },
            },
            "fallbacks": {},
        },
    )


def _single_variant_persona(slug: str) -> Persona:
    """Legacy shape: a bare string, not a list — must behave exactly as before B-147."""
    return Persona(
        slug=slug,
        display_name="B147 Legacy Test",
        geo_map_json={"default_segment": "paphos"},
        finales_json={
            "segments": {
                "paphos": {
                    "prompt_ordinal": 1,
                    "label": "Paphos",
                    "variants": {"en": _VARIANT_A},
                },
            },
            "fallbacks": {},
        },
    )


# ------------------------------------------------------------------- coerce_variant_list()

def test_coerce_variant_list_bare_string_is_one_item_list():
    assert coerce_variant_list("hello") == ["hello"]


def test_coerce_variant_list_list_passthrough():
    assert coerce_variant_list(["a", "b", "c"]) == ["a", "b", "c"]


def test_coerce_variant_list_filters_non_string_and_empty_items():
    assert coerce_variant_list(["a", "", None, 5, "b"]) == ["a", "b"]


def test_coerce_variant_list_none_or_falsy_is_empty():
    assert coerce_variant_list(None) == []
    assert coerce_variant_list("") == []
    assert coerce_variant_list([]) == []


# ------------------------------------------------------------------- get_finale_variants()

def test_get_finale_variants_returns_all_options_in_order():
    persona = _multi_variant_persona("b147-multi-order")
    assert get_finale_variants(persona, "paphos", "English") == [_VARIANT_A, _VARIANT_B, _VARIANT_C]


def test_get_finale_variants_legacy_single_string_is_one_item_list():
    persona = _single_variant_persona("b147-legacy-variants")
    assert get_finale_variants(persona, "paphos", "English") == [_VARIANT_A]


# ------------------------------------------------------------------- byte-identity per variant

def test_get_finale_text_variant_index_zero_is_byte_identical_to_variant_a():
    persona = _multi_variant_persona("b147-byte-a")
    assert get_finale_text(persona, "paphos", "English", variant_index=0) == _VARIANT_A


def test_get_finale_text_variant_index_one_is_byte_identical_to_variant_b():
    persona = _multi_variant_persona("b147-byte-b")
    assert get_finale_text(persona, "paphos", "English", variant_index=1) == _VARIANT_B


def test_get_finale_text_variant_index_two_is_byte_identical_to_variant_c():
    persona = _multi_variant_persona("b147-byte-c")
    assert get_finale_text(persona, "paphos", "English", variant_index=2) == _VARIANT_C


def test_finale_instruction_block_embeds_the_exact_variant_text_requested():
    persona = _multi_variant_persona("b147-block-embed")
    for idx, expected in enumerate((_VARIANT_A, _VARIANT_B, _VARIANT_C)):
        block = finale_instruction_block(persona, "paphos", "English", True, False, variant_index=idx)
        assert f'"{expected}"' in block


def test_get_finale_text_legacy_single_variant_ignores_variant_index_out_of_range():
    """Backward compat: a 1-item list wraps the index (0 % 1 == 0), never crashes."""
    persona = _single_variant_persona("b147-legacy-wrap")
    assert get_finale_text(persona, "paphos", "English", variant_index=0) == _VARIANT_A
    assert get_finale_text(persona, "paphos", "English", variant_index=5) == _VARIANT_A


# ------------------------------------------------------------------- pick_finale_variant_index()

def test_pick_finale_variant_index_legacy_single_variant_always_zero():
    persona = _single_variant_persona("b147-pick-legacy")
    for _ in range(10):
        assert pick_finale_variant_index(persona, "paphos", "English", False, True) == 0


def test_pick_finale_variant_index_is_within_range():
    persona = _multi_variant_persona("b147-pick-range")
    for _ in range(30):
        idx = pick_finale_variant_index(persona, "paphos", "English", False, True)
        assert idx in (0, 1, 2)


def test_pick_finale_variant_index_deterministic_with_seeded_rng():
    """Same seed -> same pick, every time (determinism requirement for reproducible tests)."""
    persona = _multi_variant_persona("b147-pick-seeded")
    picks = [
        pick_finale_variant_index(persona, "paphos", "English", False, True, rng=random.Random(42))
        for _ in range(5)
    ]
    assert len(set(picks)) == 1  # every seeded call landed on the same index


def test_pick_finale_variant_index_different_seeds_can_differ():
    """Sanity check that the rng is actually being used, not silently ignored."""
    persona = _multi_variant_persona("b147-pick-varied")
    picks = {
        pick_finale_variant_index(persona, "paphos", "English", False, True, rng=random.Random(seed))
        for seed in range(20)
    }
    assert len(picks) > 1  # different seeds produced more than one distinct index


# ------------------------------------------------------------------- critic: match ANY variant

def test_critic_strips_variant_b_and_c_not_just_variant_a():
    """B-147 requirement: the fixed-block peer-similarity exclusion must recognize any variant of
    a segment as a known, deliberately-shared closing paragraph — not only the first option."""
    from app.services.email_validation_service import _fixed_finale_blocks_cached, _strip_fixed_blocks

    persona = _multi_variant_persona("b147-critic-match")
    blocks = _fixed_finale_blocks_cached(persona)
    assert _VARIANT_A in blocks
    assert _VARIANT_B in blocks
    assert _VARIANT_C in blocks

    for variant_text in (_VARIANT_A, _VARIANT_B, _VARIANT_C):
        body = f"Hi there,\n\nSome unique opening about this recipient.\n\n{variant_text}"
        stripped = _strip_fixed_blocks(body, persona)
        assert variant_text not in stripped, f"variant not stripped: {variant_text[:40]}..."
        assert "Some unique opening about this recipient." in stripped


# ------------------------------------------------------------------- pipeline wiring: pick once, persist

def test_compose_outreach_subject_body_picks_finale_variant_once_and_persists_it(db, monkeypatch):
    """B-147: compose_outreach_subject_body must pick the variant index ONCE (not re-roll per
    retry) and surface it in generation_meta_json["finale_variant"] for persistence onto
    email_drafts.finale_variant. The rotation logic itself is covered above — this test only
    checks the pipeline wires a pre-chosen index through, so pick_finale_variant_index is
    monkeypatched to a fixed value rather than re-testing randomness here."""
    from app.models.contact import Contact
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.services import outreach_email_pipeline as pipeline

    project = Project(name="b147-pipeline-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="b147-pipeline-run")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, language="English"))
    db.commit()
    db.refresh(run)
    contact = Contact(run_id=run.id, name="Jo", email="jo@b147test.example.com", company="Acme")
    db.add(contact)
    db.commit()

    monkeypatch.setattr(pipeline, "ensure_contact_personalization", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "pick_finale_variant_index", lambda *a, **k: 2)
    monkeypatch.setattr(
        pipeline,
        "generate_email_reasoning",
        lambda *a, **k: {
            "hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": "",
        },
    )

    captured: dict = {}

    def _fake_draft(db_, run_, contact_, reasoning, **kwargs):
        captured["finale_variant_index"] = kwargs.get("finale_variant_index")
        return "Subject line", "Body text that is long enough to pass the pipeline's own checks."

    monkeypatch.setattr(pipeline, "generate_email_draft", _fake_draft)
    monkeypatch.setattr(
        pipeline, "validate_outbound_email", lambda *a, **k: {"is_valid": True, "issues": []},
    )

    subject, body, meta = pipeline.compose_outreach_subject_body(
        db, run, contact, prompt_setup_text=None, master_variant=None,
    )

    assert subject == "Subject line"
    assert captured["finale_variant_index"] == 2
    assert meta["finale_variant"] == 2


# ------------------------------------------------------------------- generation_meta_json <-> typed column

def test_generation_meta_dict_to_column_values_maps_finale_variant():
    from app.utils.email_draft_generation_meta import generation_meta_dict_to_column_values

    cols = generation_meta_dict_to_column_values({"finale_variant": 1})
    assert cols["finale_variant"] == 1


def test_generation_meta_dict_to_column_values_finale_variant_none_when_absent():
    from app.utils.email_draft_generation_meta import generation_meta_dict_to_column_values

    cols = generation_meta_dict_to_column_values({})
    assert cols["finale_variant"] is None


def test_build_generation_meta_json_from_columns_round_trips_finale_variant():
    from types import SimpleNamespace

    from app.utils.email_draft_generation_meta import build_generation_meta_json_from_columns

    draft = SimpleNamespace(finale_variant=2, validation_retries=0)
    meta = build_generation_meta_json_from_columns(draft)
    assert meta["finale_variant"] == 2


# ------------------------------------------------------------------- model column exists

def test_email_draft_finale_variant_column_persists(db):
    from app.models.contact import Contact
    from app.models.email_draft import EmailDraft
    from app.models.project import Project
    from app.models.run import Run

    project = Project(name="b147-column-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="b147-column-run")
    db.add(run)
    db.commit()
    contact = Contact(run_id=run.id, name="X", email="b147-column@example.com", company="Acme")
    db.add(contact)
    db.commit()
    draft = EmailDraft(
        run_id=run.id, contact_id=contact.id, company="Acme", to_email=contact.email,
        subject="Hi", body="Body", status="draft", finale_variant=1,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    assert draft.finale_variant == 1
