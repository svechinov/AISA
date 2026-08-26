"""Fork-transition Phase 1, Task 5: email_kind_for() must honor a persona-level toggle so a
persona without a frozen recruiting §2.3 fallback (NODA12: no vacancy-radar hook to fall back to,
and no recruiting-industry boilerplate to reproduce) gets a freely-authored, taste-rubric-judged
letter instead of being forced into AlexStaff's verbatim NO_VACANCY_OPENERS/NO_VACANCY_MIDDLE text
(email_validation_service._check_no_vacancy_conformance requires exact reproduction of that text
for is_no_vacancy=True). Default (persona=None, or no_signal_template_enabled unset/True) must stay
byte-identical to current behavior — this is the regression half of the test. 0 tokens: no LLM."""

from types import SimpleNamespace

from app.services.email_validation_service import (
    EMAIL_KIND_NO_VACANCY,
    EMAIL_KIND_VACANCY,
    email_kind_for,
)

EMPTY_PERSONALIZATION: dict = {"vacancy_signals": None}
WITH_ROLES_PERSONALIZATION: dict = {
    "vacancy_signals": {"is_hiring": True, "open_roles": [{"role": "Senior Unity Developer"}]},
}


def test_default_persona_none_empty_signals_is_no_vacancy():
    """Regression: existing AlexStaff/Stepan/Anastasia call sites pass persona=None or a persona
    with the column unset (NULL) — must resolve exactly as before this change."""
    assert email_kind_for(EMPTY_PERSONALIZATION, None) == EMAIL_KIND_NO_VACANCY


def test_persona_with_unset_toggle_empty_signals_is_no_vacancy():
    persona = SimpleNamespace(slug="alexey")  # no no_signal_template_enabled attribute at all
    assert email_kind_for(EMPTY_PERSONALIZATION, persona) == EMAIL_KIND_NO_VACANCY


def test_persona_with_explicit_true_empty_signals_is_no_vacancy():
    persona = SimpleNamespace(slug="alexey", no_signal_template_enabled=True)
    assert email_kind_for(EMPTY_PERSONALIZATION, persona) == EMAIL_KIND_NO_VACANCY


def test_persona_with_none_value_empty_signals_is_no_vacancy():
    """A live DB row backfilled by ALTER TABLE has no_signal_template_enabled=NULL, not True —
    must still resolve as True (current behavior), not fail closed."""
    persona = SimpleNamespace(slug="alexey", no_signal_template_enabled=None)
    assert email_kind_for(EMPTY_PERSONALIZATION, persona) == EMAIL_KIND_NO_VACANCY


def test_persona_toggle_disabled_empty_signals_is_vacancy():
    persona = SimpleNamespace(slug="noda12", no_signal_template_enabled=False)
    assert email_kind_for(EMPTY_PERSONALIZATION, persona) == EMAIL_KIND_VACANCY


def test_real_open_roles_always_vacancy_regardless_of_toggle():
    """Trek B (corporate/T&D): a real vacancy signal must win even if the toggle is disabled —
    the toggle only changes what happens when there is NO signal, never suppresses a real one."""
    persona = SimpleNamespace(slug="noda12", no_signal_template_enabled=False)
    assert email_kind_for(WITH_ROLES_PERSONALIZATION, persona) == EMAIL_KIND_VACANCY

    default_persona = SimpleNamespace(slug="alexey")
    assert email_kind_for(WITH_ROLES_PERSONALIZATION, default_persona) == EMAIL_KIND_VACANCY
