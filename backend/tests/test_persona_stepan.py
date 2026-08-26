"""B-071 final stage: "stepan" persona (US COO) — verbatim finale/signature text approved by
Алексей 18.07 (multitenancy-personas-handoff-2026-07-18.md decision 15а), geo-segment resolution
for the "us" segment, and the persona's field shape (EN-only, correct mailbox).

Same fixture pattern as test_geo_segment_service.py / test_persona_finale_regression.py: register
every model via pkgutil.iter_modules so FK targets resolve, then build an in-memory (non-persisted)
Persona from the exact kwargs seed_alexstaff_preset.py upserts into the DB.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.persona import Persona
from app.services.email_finale_templates import finale_instruction_block, get_finale_text
from app.services.geo_segment_service import resolve_geo_segment
from app.services.persona_service import STEPAN_SLUG, stepan_persona_kwargs

# Register every model with Base BEFORE any ORM instance (Persona(...) below) is constructed —
# SQLAlchemy configures ALL mappers in the shared registry on first use, and a relationship (e.g.
# Contact -> ContactPersonalization) fails to resolve if its target class was never imported yet.
import app.models as _models_pkg  # noqa: E402

for _, _name, _ in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"app.models.{_name}")

# Verbatim text approved by Алексей 18.07 — do not touch. Hardcoded here (independent of
# app.services.persona_service.STEPAN_FINALES_JSON) so a byte-drift in either place fails a test.
_APPROVED_EN = (
    "I'm the agency's COO and I'm based here in the States, so a call is easy to fit into your "
    "schedule. Happy to grab 15 minutes to get acquainted and talk through how we might help with "
    "your hiring — or we can just as easily keep it to email, whichever works better. What would "
    "suit you?"
)
_APPROVED_EN_EX_CIS = (
    "I'm the agency's COO and I'm based here in the States, so a call is easy to fit into your "
    "schedule. Happy to grab 15 minutes to get acquainted and talk through how we might help with "
    "your hiring — or we can just as easily continue here or on Telegram, whichever works better. "
    "What would suit you?"
)
_APPROVED_SIGNATURE_HTML = (
    "<p>Stepan Pakhanov<br>"
    "COO, AlexStaff Agency — recruiting for game studios and publishers since 2006<br>"
    '<a href="mailto:stepan@alexstaff.agency">stepan@alexstaff.agency</a> · '
    '<a href="https://alexstaff.agency">alexstaff.agency</a><br>'
    "Based in the US</p>"
    "<p>{{CAN_SPAM_POSTAL_ADDRESS}}<br>"
    "If you'd rather not hear from us, just reply \"STOP\" and I'll take you off my list.</p>"
)


@pytest.fixture()
def persona_stepan() -> Persona:
    """The "stepan" persona built from the exact data seed_alexstaff_preset.py upserts (via
    app.services.persona_service.stepan_persona_kwargs) — an in-memory, non-persisted row."""
    return Persona(**stepan_persona_kwargs())


@pytest.fixture()
def geo_session(tmp_path):
    import app.models as models_pkg
    from app.db import Base

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")

    engine = create_engine(f"sqlite:///{(tmp_path / 'stepan_regress.db').as_posix()}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_contact(session, *, company: str = "Acme"):
    from app.models.contact import Contact
    from app.models.project import Project
    from app.models.run import Run

    project = Project(name="stepan-regress", type="generic")
    session.add(project)
    session.commit()
    run = Run(project_id=project.id, workflow_name="generic_outreach", name="stepan-regress-run")
    session.add(run)
    session.commit()
    contact = Contact(run_id=run.id, company=company, email="x@acme.com", name="Jo", role="CEO")
    session.add(contact)
    session.commit()
    return contact


# ---------------------------------------------------------------------------------------------
# Byte-identity of the approved texts
# ---------------------------------------------------------------------------------------------


def test_stepan_persona_kwargs_shape(persona_stepan):
    assert persona_stepan.slug == STEPAN_SLUG
    assert persona_stepan.display_name == "Stepan Pakhanov"
    assert persona_stepan.languages_json == ["English"]
    assert persona_stepan.primary_mailbox_email == "stepan@alexstaff.agency"
    assert persona_stepan.timezone == "America/New_York"


def test_stepan_signature_byte_identical(persona_stepan):
    assert persona_stepan.signature_html == _APPROVED_SIGNATURE_HTML


def test_stepan_finale_en_byte_identical(persona_stepan):
    text = get_finale_text(persona_stepan, "us", "English", ex_cis=False, malindi=False)
    assert text == _APPROVED_EN


def test_stepan_finale_en_ex_cis_byte_identical(persona_stepan):
    text = get_finale_text(persona_stepan, "us", "English", ex_cis=True, malindi=False)
    assert text == _APPROVED_EN_EX_CIS


# ---------------------------------------------------------------------------------------------
# resolve_geo_segment: US recipient -> "us" segment; ex-CIS background -> ex_cis flag set
# ---------------------------------------------------------------------------------------------


def test_resolve_geo_segment_us_recipient_defaults_to_us_segment(geo_session, persona_stepan):
    contact = _make_contact(geo_session)
    pers = {"person_osint": {"recipient_location": "Austin, Texas"}}
    result = resolve_geo_segment(geo_session, contact, persona_stepan, pers)
    assert result["segment"] == "us"
    assert result["malindi"] is False


def test_resolve_geo_segment_no_data_defaults_to_us_segment(geo_session, persona_stepan):
    contact = _make_contact(geo_session)
    result = resolve_geo_segment(geo_session, contact, persona_stepan, {})
    assert result["segment"] == "us"
    assert result["ex_cis"] is False


def test_resolve_geo_segment_ex_cis_background_sets_flag(geo_session, persona_stepan):
    contact = _make_contact(geo_session)
    pers = {
        "person_osint": {
            "recipient_location": "New York",
            "career_summary": "Previously led engineering at a Moscow-based studio.",
        }
    }
    result = resolve_geo_segment(geo_session, contact, persona_stepan, pers)
    assert result["segment"] == "us"
    assert result["ex_cis"] is True


# ---------------------------------------------------------------------------------------------
# finale_instruction_block: prompt block renders with the "United States" label and the right
# variant, driven by resolve_geo_segment's ex_cis flag.
# ---------------------------------------------------------------------------------------------


def test_finale_instruction_block_us_label_and_text(persona_stepan):
    block = finale_instruction_block(persona_stepan, "us", "English", malindi=False, ex_cis=False)
    assert "United States" in block
    assert _APPROVED_EN in block


def test_finale_instruction_block_us_ex_cis_variant(persona_stepan):
    block = finale_instruction_block(persona_stepan, "us", "English", malindi=False, ex_cis=True)
    assert "United States" in block
    assert _APPROVED_EN_EX_CIS in block
