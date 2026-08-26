"""B-063: mechanical named-role cross-check (decision 8) + fixed-block exclusion from
peer-similarity (decision 4). Both are deterministic, testable without a DB.

B-071: finale_instruction_block/FINALE_TEMPLATES moved from module constants (int segment keys)
to persona data (string segment keys) — these tests now build the "alexey" persona and call the
persona-driven resolver, keyed the same way scripts/seed_alexstaff_preset.py seeds the DB row."""

import importlib
import pkgutil

import pytest

import app.services.email_validation_service as evs
from app.models.persona import Persona
from app.services.persona_service import alexey_persona_kwargs

# Register every model with Base BEFORE any ORM instance (Persona(...) below) is constructed —
# SQLAlchemy configures ALL mappers in the shared registry on first use, and a relationship (e.g.
# Contact -> ContactPersonalization) fails to resolve if its target class was never imported yet.
import app.models as _models_pkg  # noqa: E402

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")


@pytest.fixture()
def persona_alexey() -> Persona:
    return Persona(**alexey_persona_kwargs())


# --- Fixed-block stripping (item 13: "вычитание фиксблоков") ---

FINALE_2_EN = (
    "I co-founded the agency; I live in Paphos but I'm in Limassol most weeks — I'd gladly drop "
    "by for a coffee to get acquainted and talk through how we might work together, or we could "
    "catch each other any Wednesday at the iT_Party at Malindi. Or simply a 15-minute "
    "call. What works best for you?"
)

OPENER_EN = (
    "We're AlexStaff — an IT-recruiting agency, recruiting for game studios and publishers "
    "since 2006."
)


def test_finale_paragraph_is_stripped_verbatim():
    body = f"Hi Alex,\n\nSome hook sentence about the company.\n\n{FINALE_2_EN}"
    stripped = evs._strip_fixed_blocks(body)
    assert "Malindi" not in stripped
    assert "Some hook sentence" in stripped


def test_finale_paragraph_stripped_with_synonym_leeway():
    """Synonym-level leeway (happy<->glad, quick<->short) must still fuzzy-match and strip."""
    varied = FINALE_2_EN.replace("gladly", "happily").replace("simply a 15-minute", "just a quick 15-minute")
    body = f"Hi Alex,\n\nHook.\n\n{varied}"
    stripped = evs._strip_fixed_blocks(body)
    assert "Malindi" not in stripped
    assert "Hook" in stripped


def test_who_we_are_block_stripped_hook_survives():
    # The standing who-we-are block (opener sentence + shared proof) is dropped; the
    # recipient-specific hook paragraph is kept.
    body = f"Hi Alex,\n\nAcme just opened three engineering roles.\n\n{OPENER_EN} We grew the Broken Sun team from 30 to about 260 people through open beta."
    stripped = evs._strip_fixed_blocks(body)
    assert "AlexStaff — an IT-recruiting agency" not in stripped
    assert "Acme just opened" in stripped


def test_shared_no_vacancy_proof_paragraph_is_stripped():
    # #7: the wave-identical who-we-are + Broken Sun/Helio proof paragraph must be stripped whole
    # so two no-vacancy emails do not collide on duplicate_peer.
    from app.services.outreach_email_pipeline import NO_VACANCY_MIDDLE

    proof_para = NO_VACANCY_MIDDLE["en"].split("\n\n")[0]
    body = f"Hi Alex,\n\nAcme just shipped a new title.\n\n{proof_para}"
    stripped = evs._strip_fixed_blocks(body)
    assert "Broken Sun" not in stripped
    assert "Acme just shipped" in stripped


def test_non_fixed_body_is_unchanged_in_substance():
    body = "Hi Alex,\n\nSomething entirely specific to this recipient.\n\nAnother unique paragraph."
    stripped = evs._strip_fixed_blocks(body)
    assert "Something entirely specific" in stripped
    assert "Another unique paragraph" in stripped


def test_shared_finale_does_not_trigger_duplicate_peer(monkeypatch):
    """The whole point of decision 4: two wave emails sharing only the closing paragraph must
    not be flagged as duplicates."""
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])  # no LLM in this test
    body_a = f"Hi Alex,\n\nAcme just opened three engineering roles.\n\n{OPENER_EN}\n\n{FINALE_2_EN}"
    body_b = f"Hi Jo,\n\nBeta Studio is scaling its art team fast.\n\n{OPENER_EN}\n\n{FINALE_2_EN}"

    result = evs.validate_outbound_email("Subject A", body_a, {}, [body_b])
    assert not any(i["code"] == "duplicate_peer" for i in result["issues"])


def test_identical_non_fixed_content_still_flagged_duplicate(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])
    body_a = f"Hi Alex,\n\n{FINALE_2_EN}"
    body_b = f"Hi Alex,\n\n{FINALE_2_EN}"  # identical even after stripping the finale (nothing left but greeting)

    result = evs.validate_outbound_email("Subject", body_a, {}, [body_b])
    assert any(i["code"] == "duplicate_peer" for i in result["issues"])


# --- Named-role cross-check (item 13: "механическая сверка ролей") ---

def test_roles_match_exact():
    assert evs._roles_match("Senior Unity Developer", ["Senior Unity Developer"])


def test_roles_match_fuzzy_overlap():
    assert evs._roles_match("Unity Developer", ["Senior Unity Developer (Cyprus)"])


def test_roles_match_false_for_unrelated_role():
    assert not evs._roles_match("Head of Recruitment", ["Senior Unity Developer"])


def test_check_named_roles_none_when_nothing_named(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: [])
    assert evs._check_named_roles("Hi, generic body.", {"vacancy_signals": None}) is None


def test_check_named_roles_rejects_when_vacancy_signals_empty(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: ["Senior Unity Developer"])
    issue = evs._check_named_roles("... Senior Unity Developer ...", {"vacancy_signals": None})
    assert issue is not None and issue["code"] == "invented_role"


def test_check_named_roles_rejects_unmatched_role(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: ["Head of Recruitment"])
    pers = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer"}]}}
    issue = evs._check_named_roles("...", pers)
    assert issue is not None and issue["code"] == "invented_role"


def test_check_named_roles_passes_matched_role(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: ["Senior Unity Developer"])
    pers = {"vacancy_signals": {"open_roles": [{"role": "Senior Unity Developer", "location": "Limassol"}]}}
    assert evs._check_named_roles("...", pers) is None


def test_validate_outbound_email_rejects_invented_role(monkeypatch):
    monkeypatch.setattr(evs, "_extract_named_roles", lambda body: ["Match-3 Artist"])
    body = "Hi Alex,\n\nWe saw you're hiring a Match-3 Artist.\n\n" + OPENER_EN
    result = evs.validate_outbound_email("Subject", body, {"vacancy_signals": None}, [])
    assert result["is_valid"] is False
    assert any(i["code"] == "invented_role" for i in result["issues"])


# --- Finale selection: iT_Party naming + no-Malindi verbatim variants (approved 2026-07-16) ---

def test_segment_2_no_malindi_returns_dedicated_verbatim_text(persona_alexey):
    from app.services.email_finale_templates import finale_instruction_block

    block = finale_instruction_block(persona_alexey, "limassol", "English", malindi=False, ex_cis=False)
    assert "Malindi" not in block
    assert "iT_Party" not in block
    assert "Drop any mention" not in block
    assert "segment 2/Limassol" in block


def test_segment_4_no_malindi_collapses_to_segment_3_no_malindi_verbatim(persona_alexey):
    from app.services.email_finale_templates import finale_instruction_block

    block = finale_instruction_block(persona_alexey, "cyprus_other", "English", malindi=False, ex_cis=False)
    assert "segment 3/Larnaca/Nicosia" in block
    assert "Malindi" not in block
    assert "Drop any mention" not in block


def test_segment_2_with_malindi_uses_it_party_wording(persona_alexey):
    from app.services.email_finale_templates import finale_instruction_block

    block = finale_instruction_block(persona_alexey, "limassol", "English", malindi=True, ex_cis=True)
    assert "iT_Party at Malindi" in block
    assert "IT get-together" not in block


def test_no_malindi_variants_are_picked_up_by_fixed_block_cache(persona_alexey):
    """The critic's peer-similarity exclusion (_fixed_finale_blocks_cached) iterates all finale
    variants of the persona — the ru_no_malindi/en_no_malindi keys must be caught automatically,
    with no separate registration needed."""
    segments = persona_alexey.finales_json["segments"]

    evs._fixed_finale_blocks = {}  # reset the per-persona cache so this test is order-independent
    blocks = evs._fixed_finale_blocks_cached(persona_alexey)
    assert segments["limassol"]["variants"]["en_no_malindi"] in blocks
    assert segments["limassol"]["variants"]["ru_no_malindi"] in blocks
    assert segments["larnaca_nicosia"]["variants"]["en_no_malindi"] in blocks
    assert segments["larnaca_nicosia"]["variants"]["ru_no_malindi"] in blocks
