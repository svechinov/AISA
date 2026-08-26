"""B-128 Phase 3: --profile {cyprus,us} flag on scripts/seed_alexstaff_preset.py.

Without --profile (or with --profile cyprus) the script must sync exactly what it synced before
this flag existed - byte-for-byte. --profile us overlays sender (Stepan) and ICP for the US run
on top of the shared canon core, never touching PROMPT_SETUP_TEXT / DEFAULT_CRITIC_CANON / HARD
RULES / finales. See docs/us-email-canon-2026-07-20.md (sections 1-2, the single source of truth
for the overlay text).
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is a plain directory (no __init__.py, not baked into the prod image - see CLAUDE.md
# "Грабли") - import it the same way the script imports its own backend/ parent, by path.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_alexstaff_preset as seed  # noqa: E402
from app.services.persona_service import (  # noqa: E402
    CAN_SPAM_ADDRESS_PLACEHOLDER,
    stepan_persona_kwargs,
)


# ---------------------------------------------------------------------------------------------
# default / cyprus profile: byte-for-byte regression against the pre-existing canon
# ---------------------------------------------------------------------------------------------


def test_default_profile_matches_module_canon_dicts():
    """No profile passed -> same dicts as before this flag existed (same objects, not just equal)."""
    text_fields, scalar_fields = seed._canon_fields_for_profile()
    assert text_fields is seed.CANON_TEXT_FIELDS
    assert scalar_fields is seed.CANON_SCALAR_FIELDS


def test_cyprus_profile_matches_module_canon_dicts():
    text_fields, scalar_fields = seed._canon_fields_for_profile("cyprus")
    assert text_fields is seed.CANON_TEXT_FIELDS
    assert scalar_fields is seed.CANON_SCALAR_FIELDS


def test_cyprus_profile_prompt_is_untouched_core():
    text_fields, _ = seed._canon_fields_for_profile("cyprus")
    assert text_fields["prompt_setup_text"] == seed.PROMPT_SETUP_TEXT


def test_cyprus_profile_signature_is_alexey():
    text_fields, _ = seed._canon_fields_for_profile("cyprus")
    assert text_fields["sender_signature_html"] == seed.SIGNATURE_HTML


def test_cyprus_profile_icp_is_10_500_cyprus():
    _, scalar_fields = seed._canon_fields_for_profile("cyprus")
    assert scalar_fields["icp_min_employees"] == 10
    assert scalar_fields["icp_max_employees"] == 500
    assert scalar_fields["icp_criteria_json"]["regions"] == ["Cyprus"]


# ---------------------------------------------------------------------------------------------
# us profile: overlay on top of the untouched core, Stepan signature, US ICP
# ---------------------------------------------------------------------------------------------


def test_us_profile_prompt_starts_with_untouched_core_and_has_overlay():
    text_fields, _ = seed._canon_fields_for_profile("us")
    prompt = text_fields["prompt_setup_text"]
    assert prompt.startswith(seed.PROMPT_SETUP_TEXT)
    assert seed.US_PROFILE_OVERLAY in prompt
    # exact join: core + blank line + overlay, nothing else added or reworded
    assert prompt == seed.PROMPT_SETUP_TEXT + "\n\n" + seed.US_PROFILE_OVERLAY


def test_us_profile_does_not_mutate_core_constant():
    """Building the us profile must never rewrite the module-level core constant itself."""
    before = seed.PROMPT_SETUP_TEXT
    seed._canon_fields_for_profile("us")
    assert seed.PROMPT_SETUP_TEXT == before


def test_us_profile_signature_is_stepan_with_can_spam_placeholder():
    text_fields, _ = seed._canon_fields_for_profile("us")
    signature = text_fields["sender_signature_html"]
    assert signature == stepan_persona_kwargs()["signature_html"]
    assert CAN_SPAM_ADDRESS_PLACEHOLDER in signature


def test_us_profile_icp_is_30_200_united_states():
    _, scalar_fields = seed._canon_fields_for_profile("us")
    assert scalar_fields["icp_min_employees"] == 30
    assert scalar_fields["icp_max_employees"] == 200
    assert scalar_fields["icp_criteria_json"]["regions"] == ["United States"]
    assert (
        scalar_fields["icp_criteria_json"]["industry_keywords"]
        == seed.CANON_ICP_CRITERIA_JSON["industry_keywords"]
    )


def test_us_profile_leaves_critic_canon_untouched():
    text_fields, _ = seed._canon_fields_for_profile("us")
    assert text_fields["critic_canon_text"] == seed.DEFAULT_CRITIC_CANON


# ---------------------------------------------------------------------------------------------
# dry-run path and write path must read the same values for a given profile (no divergence)
# ---------------------------------------------------------------------------------------------


def test_dry_run_and_write_paths_get_identical_fields_for_same_profile():
    """main() calls _canon_fields_for_profile(args.profile) once for the dry-run diff and once
    (on a real, separate invocation) for the write - both must resolve to equal values for the
    same profile, since it's the same pure function of the same input."""
    for profile in ("cyprus", "us"):
        first_text, first_scalar = seed._canon_fields_for_profile(profile)
        second_text, second_scalar = seed._canon_fields_for_profile(profile)
        assert first_text == second_text
        assert first_scalar == second_scalar
