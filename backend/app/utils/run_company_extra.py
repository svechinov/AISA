"""Run company extra fields: entity_json_kv scope run_company_extra (replaces run_companies.extra_json)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_RUN_COMPANY_EXTRA
from app.models.run_company import RunCompany
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_run_company_extra(db: Session, row: RunCompany) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_RUN_COMPANY_EXTRA,
        row.id,
        row.extra_json,
        clear_legacy=lambda: setattr(row, "extra_json", {}),
    )


def persist_run_company_extra(db: Session, row: RunCompany, data: dict[str, Any] | None) -> None:
    raw = dict(data or {})
    raw.pop("contact_status", None)
    replace_kv_dict(db, SCOPE_RUN_COMPANY_EXTRA, row.id, raw or None)
    row.extra_json = {}
    # Evidence Store: this is the single choke point where dossiers are written (enrich,
    # row re-creation in sync_run_companies_from_dicts, future writers) — index here so
    # company_evidence can never silently drift from the KV dossier. Never fatal.
    if "osint_dossier" in raw:
        try:
            from app.services.evidence_store import sync_company_evidence_from_dossier

            # SAVEPOINT: a failed sync rolls back only itself — the dossier persist above
            # survives and the session stays usable for the rest of the enrich loop.
            with db.begin_nested():
                sync_company_evidence_from_dossier(db, row, raw.get("osint_dossier"))
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Evidence sync failed for run_company id=%s (dossier kept, index stale)", row.id
            )
