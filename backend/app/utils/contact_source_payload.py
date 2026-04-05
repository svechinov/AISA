"""Contact source: entity_json_kv (scope contact_source); legacy column cleared on first read."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_CONTACT_SOURCE
from app.models.contact import Contact
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_contact_source_json(db: Session, contact: Contact) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_CONTACT_SOURCE,
        contact.id,
        contact.source_json,
        clear_legacy=lambda: setattr(contact, "source_json", {}),
    )


def persist_contact_source(db: Session, contact: Contact, data: dict[str, Any] | None) -> None:
    replace_kv_dict(db, SCOPE_CONTACT_SOURCE, contact.id, data or None)
    contact.source_json = {}
