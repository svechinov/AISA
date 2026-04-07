"""Remove one collected company row and matching contacts for a run."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RUN_COMPANY_EXTRA
from app.models.contact import Contact
from app.models.run_company import RunCompany
from app.repositories.run_company_repo import get_company_dict_at_index
from app.repositories.run_repo import get_run
from app.services.contact_persistence_service import contact_row_to_pipeline_dict
from app.services.run_companies_status_service import _contact_matches_company, _entity_keys
from app.services.run_deletion_service import delete_contacts_cascade
from app.utils.entity_kv_storage import delete_scope


def delete_collected_company_at_index(db: Session, run_id: int, collect_index: int) -> dict:
    """
    Delete ``run_companies`` row at ``collect_index`` and contacts whose keys match that company.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed")

    rc = (
        db.query(RunCompany)
        .filter(RunCompany.run_id == run_id, RunCompany.collect_index == collect_index)
        .first()
    )
    if not rc:
        raise ValueError("Company row not found")

    company_row = get_company_dict_at_index(db, run_id, collect_index)
    if not company_row:
        raise ValueError("Company row not found")

    ckeys = _entity_keys(company_row)
    contact_ids: list[int] = []
    for c in db.query(Contact).filter(Contact.run_id == run_id).all():
        d = contact_row_to_pipeline_dict(db, c)
        if _contact_matches_company(d, ckeys):
            contact_ids.append(c.id)

    removed = delete_contacts_cascade(db, contact_ids, commit=False)

    delete_scope(db, SCOPE_RUN_COMPANY_EXTRA, rc.id)
    db.delete(rc)
    db.commit()

    return {
        "deleted_collect_index": collect_index,
        "contacts_removed": removed,
    }
