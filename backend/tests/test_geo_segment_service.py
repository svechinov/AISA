"""B-063: geo_segment_service — recipient-location cascade, segments, Malindi/ex-CIS filter.

Standalone temp SQLite (no snapshot needed) — same pattern as
test_draft_instruct_edit.py::test_instruct_log_model_roundtrip: register all models via
pkgutil.iter_modules so FK targets resolve, then create_all on a throwaway engine.

B-071: resolve_geo_segment now takes the sending persona explicitly and returns the persona's
string segment keys (paphos/limassol/larnaca_nicosia/cyprus_other/outside for alexey) instead of
the old global int 1-5 — these tests build the "alexey" persona (same data
scripts/seed_alexstaff_preset.py seeds into the DB) and assert against its segment keys.
"""

import importlib
import pkgutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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


@pytest.fixture()
def session(tmp_path):
    import app.models as models_pkg
    from app.db import Base

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"app.models.{name}")

    engine = create_engine(f"sqlite:///{(tmp_path / 'geo.db').as_posix()}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_contact(session: Session, *, company: str = "Acme") -> "Contact":  # noqa: F821
    from app.models.contact import Contact
    from app.models.project import Project
    from app.models.run import Run

    project = Project(name="geo-test", type="generic")
    session.add(project)
    session.commit()
    run = Run(project_id=project.id, workflow_name="generic_outreach", name="geo-run")
    session.add(run)
    session.commit()
    contact = Contact(run_id=run.id, company=company, email="x@acme.com", name="Jo", role="CEO")
    session.add(contact)
    session.commit()
    return contact


def test_recipient_location_top_of_cascade_paphos(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {"person_osint": {"recipient_location": "Paphos, Cyprus"}}
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out["segment"] == "paphos"


def test_recipient_location_limassol(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {"person_osint": {"recipient_location": "Limassol"}}
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out["segment"] == "limassol"


def test_recipient_location_larnaca_or_nicosia(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    assert resolve_geo_segment(
        session, contact, persona_alexey, {"person_osint": {"recipient_location": "Larnaca"}}
    )["segment"] == "larnaca_nicosia"
    assert resolve_geo_segment(
        session, contact, persona_alexey, {"person_osint": {"recipient_location": "Nicosia"}}
    )["segment"] == "larnaca_nicosia"


def test_cyprus_without_city_is_segment_4(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {"person_osint": {"recipient_location": "Cyprus"}}
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out["segment"] == "cyprus_other"


def test_no_data_anywhere_defaults_to_segment_5(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    out = resolve_geo_segment(session, contact, persona_alexey, {})
    assert out == {"segment": "outside", "malindi": False, "ex_cis": False}


def test_cascade_falls_back_to_company_office_city(session, persona_alexey):
    """No recipient_location -> company_evidence facts (city text) resolve the segment."""
    from app.models.company_evidence import CompanyEvidence
    from app.models.run_company import RunCompany
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session, company="Nekki")
    rc = RunCompany(run_id=contact.run_id, collect_index=1, name="Nekki", website="nekki.com")
    session.add(rc)
    session.commit()
    session.add(CompanyEvidence(run_company_id=rc.id, run_id=contact.run_id, kind="evidence",
                                 fact="Office address: Kimonos 43A, Limassol, Cyprus"))
    session.commit()

    out = resolve_geo_segment(session, contact, persona_alexey, {})
    assert out["segment"] == "limassol"


def test_cascade_falls_back_to_osint_dossier_text_for_country(session, persona_alexey):
    """No recipient_location, no evidence rows -> osint_dossier KV text (country-only mention)."""
    from app.models.run_company import RunCompany
    from app.services.geo_segment_service import resolve_geo_segment
    from app.utils.run_company_extra import persist_run_company_extra

    contact = _make_contact(session, company="Playnetic")
    rc = RunCompany(run_id=contact.run_id, collect_index=1, name="Playnetic", website="playnetic.com")
    session.add(rc)
    session.commit()
    persist_run_company_extra(session, rc, {"osint_dossier": '{"evidence": [{"fact": "Headquartered in Valletta, Malta"}]}'})
    session.commit()

    out = resolve_geo_segment(session, contact, persona_alexey, {})
    # "Malta" isn't Cyprus and no city keyword matches -> safe default (outside), never a guess.
    assert out["segment"] == "outside"


def test_company_text_ignores_incidental_and_closed_cities(session, persona_alexey):
    """#5: a city named without address context (competitor/remote), or next to a closure marker
    (closed/former office), must NOT drive a specific-city segment."""
    from app.services.geo_segment_service import _segment_from_company_text

    assert _segment_from_company_text("HQ in London; closed their Limassol office in 2022, now remote", persona_alexey) is None
    assert _segment_from_company_text("Our biggest competitor sits in Paphos; we ship worldwide", persona_alexey) is None
    # A real office address still resolves; two conflicting offices -> Cyprus-no-city, not a guess.
    assert _segment_from_company_text("Office address: Kimonos 43A, Limassol, Cyprus", persona_alexey) == "limassol"
    assert _segment_from_company_text("Offices in Paphos and Limassol", persona_alexey) == "cyprus_other"


def test_ex_cis_substring_false_positives_killed():
    """#6: word-boundary matching stops 'рф' inside 'перформанс', 'baku' inside 'табаку'."""
    from app.services.geo_segment_service import _text_has_any
    from app.services.persona_service import ALEXEY_GEO_MAP_JSON

    ex_cis_keywords = tuple(ALEXEY_GEO_MAP_JSON["ex_cis_keywords"])
    assert not _text_has_any("оптимизация перформанса и серфинг", ex_cis_keywords)
    assert not _text_has_any("любит табаку", ex_cis_keywords)
    assert _text_has_any("previously at a Moscow studio", ex_cis_keywords)


def test_ex_cis_background_enables_malindi(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {
        "person_osint": {
            "recipient_location": "Limassol",
            "career_summary": "Previously led engineering at a Moscow-based studio.",
        }
    }
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out == {"segment": "limassol", "malindi": True, "ex_cis": True}


def test_no_ex_cis_evidence_keeps_malindi_off(session, persona_alexey):
    """Decision 3: absence of ex-CIS evidence is a conservative default, not a guess either way."""
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {"person_osint": {"recipient_location": "Limassol", "career_summary": "Led product at a Berlin studio."}}
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out == {"segment": "limassol", "malindi": False, "ex_cis": False}


def test_segment_5_never_gets_malindi_even_with_ex_cis(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    pers = {"person_osint": {"recipient_location": "Belgrade", "career_summary": "Moscow, Russia born and raised."}}
    out = resolve_geo_segment(session, contact, persona_alexey, pers)
    assert out["segment"] == "outside"
    assert out["malindi"] is False


def test_malformed_personalization_does_not_raise(session, persona_alexey):
    from app.services.geo_segment_service import resolve_geo_segment

    contact = _make_contact(session)
    out = resolve_geo_segment(session, contact, persona_alexey, {"person_osint": "not-a-dict"})  # type: ignore[arg-type]
    assert out == {"segment": "outside", "malindi": False, "ex_cis": False}
