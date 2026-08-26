"""B-158: the closing paragraph is appended to the body in CODE after LLM generation, never
written by the model — this guarantees byte-exactness by construction. Root cause this fixes: the
LLM occasionally rewrote the "verbatim" closing paragraph in its own words (e.g. to dodge HARD
RULE 15's em dash ban), producing drafts whose finale_variant metadata said "0" (variant A) while
the actual text in the body was self-invented and did not match any real variant.

Also covers the critic's hard byte-gate (validate_outbound_email's expected_finale_variants):
mismatch is a critical failure, same severity as invented_role.
"""

from __future__ import annotations

import importlib
import pkgutil

# Register every model with Base before any ORM instance is constructed (same guard as the other
# B-14x test files — SQLAlchemy mapper configuration needs every model module imported first).
import app.models as _models_pkg

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

from app.services.email_validation_service import validate_outbound_email  # noqa: E402


# ------------------------------------------------------------------- generate_email_draft appends verbatim

def test_generate_email_draft_appends_byte_exact_finale_regardless_of_llm_output(db, monkeypatch):
    from app.models.contact import Contact
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.services import outreach_email_pipeline as pipeline
    from app.services.email_finale_templates import get_finale_text

    project = Project(name="b158-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="b158-run")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, language="English"))
    db.commit()
    db.refresh(run)
    contact = Contact(run_id=run.id, name="Jo", email="jo@b158test.example.com", company="Acme")
    db.add(contact)
    db.commit()

    # Simulate the model ignoring the "do not write a closing" instruction and inventing its own —
    # the fix must produce the byte-exact appended finale regardless of what the model wrote.
    fake_body_from_llm = (
        "Hi Jo,\n\nAcme is hiring several roles right now.\n\n"
        "We can help by bringing you excited candidates.\n\n"
        "I'd love to continue over email if that is easier, let me know!"
    )
    monkeypatch.setattr(
        pipeline, "generate_json",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "subject": "Filling Acme's roles", "body": fake_body_from_llm
        },
    )

    reasoning = {"hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": ""}
    subject, body = pipeline.generate_email_draft(
        db, run, contact, reasoning,
        prompt_setup_text=None, master_variant=None, style_mode="default",
        pers={"vacancy_signals": None}, finale_variant_index=0,
    )

    persona = pipeline.get_run_persona(db, run)
    geo = pipeline.resolve_geo_segment(db, contact, persona, {"vacancy_signals": None})
    eff = pipeline.effective_segment_for_malindi(persona, geo["segment"], geo["malindi"])
    expected_finale = get_finale_text(
        persona, eff, "English", geo["ex_cis"], geo["malindi"], variant_index=0,
    )

    assert expected_finale, "test setup produced an empty expected finale — fix the test fixture"
    assert body.endswith(expected_finale)
    # The model's own attempted closing must still be present earlier in the body (untouched) —
    # this proves the fix APPENDS rather than silently replacing/hiding model output.
    assert "I'd love to continue over email" in body


def test_generate_email_draft_different_variant_indices_produce_different_byte_exact_endings(db, monkeypatch):
    """Sanity check that the append is wired to the SAME finale_variant_index the caller picked —
    not hardcoded to index 0."""
    from app.models.contact import Contact
    from app.models.persona import Persona
    from app.models.project import Project
    from app.models.run import Run
    from app.models.run_setup import RunSetup
    from app.services import outreach_email_pipeline as pipeline
    from app.services.email_finale_templates import get_finale_text

    persona = Persona(
        slug="b158-multi-variant",
        display_name="B158 Test",
        geo_map_json={"default_segment": "paphos"},
        finales_json={
            "segments": {
                "paphos": {
                    "prompt_ordinal": 1,
                    "label": "Paphos",
                    "variants": {"en": ["Variant A text.", "Variant B text.", "Variant C text."]},
                },
            },
            "fallbacks": {},
        },
    )

    project = Project(name="b158-multi-test", type="generic")
    db.add(project)
    db.commit()
    run = Run(project_id=project.id, workflow_name="outreach", name="b158-multi-run")
    db.add(run)
    db.commit()
    db.add(RunSetup(run_id=run.id, language="English"))
    db.commit()
    db.refresh(run)
    contact = Contact(run_id=run.id, name="Jo", email="jo@b158multitest.example.com", company="Acme")
    db.add(contact)
    db.commit()

    monkeypatch.setattr(pipeline, "get_run_persona", lambda db_, run_: persona)
    monkeypatch.setattr(
        pipeline, "resolve_geo_segment",
        lambda db_, contact_, persona_, pers_: {"segment": "paphos", "malindi": True, "ex_cis": False},
    )
    monkeypatch.setattr(
        pipeline, "generate_json",
        lambda prompt, task_kind=None, cache_prefix=None: {
            "subject": "Subj",
            "body": (
                "Hi Jo,\n\nAcme is hiring for several roles right now, which is a lot to coordinate "
                "at once. We can help by bringing you candidates who are genuinely excited about "
                "the studio, not just another CV in the pile."
            ),
        },
    )

    reasoning = {"hook": "", "angle": "", "problem": "", "solution": "", "cta_type": "", "key_point": ""}
    for idx, expected_text in enumerate(("Variant A text.", "Variant B text.", "Variant C text.")):
        _subject, body = pipeline.generate_email_draft(
            db, run, contact, reasoning,
            prompt_setup_text=None, master_variant=None, style_mode="default",
            pers={"vacancy_signals": None}, finale_variant_index=idx,
        )
        assert body.endswith(expected_text)


# ------------------------------------------------------------------- critic hard byte-gate

_OUTSIDE_FINALE = (
    "I co-founded the agency - I'm based in Cyprus myself. Happy to jump on a quick "
    "15-minute call, or we can just as easily continue over email, whichever is easier. "
    "What would suit you?"
)


def test_validate_outbound_email_finale_verbatim_mismatch_is_critical():
    body = "Hi Jo,\n\nSome real content about the role.\n\nLet's continue over email, best regards."
    result = validate_outbound_email(
        "Subject", body, {"vacancy_signals": {"open_roles": [{"role": "Unity Developer"}]}}, [],
        expected_finale_variants=[_OUTSIDE_FINALE],
    )
    assert result["is_valid"] is False
    assert any(i["code"] == "finale_verbatim_mismatch" for i in result["issues"])


def test_validate_outbound_email_finale_verbatim_match_does_not_trip_gate():
    body = f"Hi Jo,\n\nSome real content about the role.\n\n{_OUTSIDE_FINALE}"
    result = validate_outbound_email(
        "Subject", body, {"vacancy_signals": {"open_roles": [{"role": "Unity Developer"}]}}, [],
        expected_finale_variants=[_OUTSIDE_FINALE],
    )
    assert not any(i["code"] == "finale_verbatim_mismatch" for i in result["issues"])


def test_validate_outbound_email_finale_gate_recognizes_any_of_several_variants():
    variant_b = "Some other approved variant text."
    body = f"Hi Jo,\n\nSome real content about the role.\n\n{variant_b}"
    result = validate_outbound_email(
        "Subject", body, {"vacancy_signals": {"open_roles": [{"role": "Unity Developer"}]}}, [],
        expected_finale_variants=[_OUTSIDE_FINALE, variant_b],
    )
    assert not any(i["code"] == "finale_verbatim_mismatch" for i in result["issues"])


def test_validate_outbound_email_no_expected_variants_skips_gate_entirely():
    """Backward compat: callers that haven't threaded a persona/segment through (expected_finale_
    variants=None, the default) must not trip the gate — old behavior preserved."""
    body = "Hi Jo,\n\nSome real content about the role.\n\nWhatever ending, no gate applies here."
    result = validate_outbound_email(
        "Subject", body, {"vacancy_signals": {"open_roles": [{"role": "Unity Developer"}]}}, [],
    )
    assert not any(i["code"] == "finale_verbatim_mismatch" for i in result["issues"])
