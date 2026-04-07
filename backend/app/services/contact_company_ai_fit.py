"""Attach ``run_companies.ai_fit_status`` to contacts by entity-key match (company + website)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.services.contact_persistence_service import contact_row_to_pipeline_dict
from app.services.run_companies_status_service import _contact_matches_company, _entity_keys


def _ai_fit_lookups_for_run(db: Session, run_id: int) -> list[tuple[set[str], str]]:
    rows = (
        db.query(RunCompany)
        .filter(
            RunCompany.run_id == run_id,
            RunCompany.ai_fit_status.in_(("correct", "incorrect")),
        )
        .order_by(RunCompany.collect_index.asc())
        .all()
    )
    out: list[tuple[set[str], str]] = []
    for r in rows:
        keys = _entity_keys({"name": str(r.name or ""), "website": str(r.website or "")})
        if not keys:
            continue
        st = r.ai_fit_status
        if isinstance(st, str) and st in ("correct", "incorrect"):
            out.append((keys, st))
    return out


def company_ai_fit_status_for_contact(
    db: Session,
    run_id: int,
    contact: Contact,
    lookups: list[tuple[set[str], str]] | None = None,
) -> str | None:
    """Return ``correct`` / ``incorrect`` if a collected company row matches this contact."""
    cdict = contact_row_to_pipeline_dict(db, contact)
    lu = lookups if lookups is not None else _ai_fit_lookups_for_run(db, run_id)
    for company_keys, st in lu:
        if _contact_matches_company(cdict, company_keys):
            return st
    return None


def contact_reads_for_run_with_ai_fit(db: Session, run_id: int, contacts: list[Contact]):
    from app.schemas.contact import contact_read_for_run_list

    lookups = _ai_fit_lookups_for_run(db, run_id)
    return [
        contact_read_for_run_list(
            c,
            company_ai_fit_status=company_ai_fit_status_for_contact(db, run_id, c, lookups),
        )
        for c in contacts
    ]


def contact_read_with_ai_fit(db: Session, contact: Contact):
    from app.schemas.contact import contact_read_for_run_list

    st = company_ai_fit_status_for_contact(db, contact.run_id, contact)
    return contact_read_for_run_list(contact, company_ai_fit_status=st)
