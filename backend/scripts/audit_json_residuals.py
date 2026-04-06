#!/usr/bin/env python3
"""Offline audit: detect legacy JSON blob columns still populated while KV/relational store is canonical.

Run from repo:  cd backend && python scripts/audit_json_residuals.py
Exit 0 if no duplicate leftovers; exit 1 if any row violates the invariant (or DB error).

This complements startup strips in app.init_db and migrate_domain_json_to_relational.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.constants.entity_kv_scope import (  # noqa: E402
    SCOPE_ASSET_METADATA,
    SCOPE_ASSET_PACKET,
    SCOPE_CONTACT_SOURCE,
    SCOPE_RUN_COMPANY_EXTRA,
    SCOPE_STEP_INPUT,
    SCOPE_STEP_OUTPUT,
)
from app.db import SessionLocal  # noqa: E402
from app.models.asset import Asset  # noqa: E402
from app.models.asset_packet import AssetPacket  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.email_draft import EmailDraft  # noqa: E402
from app.models.run_company import RunCompany  # noqa: E402
from app.models.step import Step  # noqa: E402
from app.models.template import Template  # noqa: E402
from app.models.template_variable import TemplateVariable  # noqa: E402
from app.utils.entity_kv_storage import get_kv_dict  # noqa: E402


def _nonempty_blob(d: dict | None) -> bool:
    return bool(d and isinstance(d, dict))


def audit(db) -> list[tuple[str, int]]:
    """Return list of (label, violation_count)."""
    violations: list[tuple[str, int]] = []

    n = 0
    for a in db.query(Asset).order_by(Asset.id.asc()).all():
        if get_kv_dict(db, SCOPE_ASSET_METADATA, a.id) and _nonempty_blob(a.metadata_json if isinstance(a.metadata_json, dict) else {}):
            n += 1
    if n:
        violations.append(("assets: metadata_json nonempty while KV asset_metadata exists", n))

    n = 0
    for p in db.query(AssetPacket).order_by(AssetPacket.id.asc()).all():
        pj = p.packet_json if isinstance(p.packet_json, dict) else {}
        if get_kv_dict(db, SCOPE_ASSET_PACKET, p.id) and _nonempty_blob(pj):
            n += 1
    if n:
        violations.append(("asset_packets: packet_json nonempty while KV asset_packet exists", n))

    n = 0
    for rc in db.query(RunCompany).order_by(RunCompany.id.asc()).all():
        ej = rc.extra_json if isinstance(rc.extra_json, dict) else {}
        if get_kv_dict(db, SCOPE_RUN_COMPANY_EXTRA, rc.id) and _nonempty_blob(ej):
            n += 1
    if n:
        violations.append(("run_companies: extra_json nonempty while KV run_company_extra exists", n))

    n = 0
    for t in db.query(Template).order_by(Template.id.asc()).all():
        vj = t.variables_json if isinstance(t.variables_json, dict) else {}
        if _nonempty_blob(vj) and db.query(TemplateVariable).filter(TemplateVariable.template_id == t.id).first():
            n += 1
    if n:
        violations.append(("templates: variables_json nonempty while template_variables rows exist", n))

    n = 0
    for d in db.query(EmailDraft).filter(EmailDraft.pipeline_source.isnot(None)).all():
        if d.generation_meta_json is not None:
            n += 1
    if n:
        violations.append(
            ("email_drafts: generation_meta_json set for pipeline_source rows (should be stripped to typed cols)", n),
        )

    n = 0
    for c in db.query(Contact).order_by(Contact.id.asc()).all():
        sj = c.source_json if isinstance(c.source_json, dict) else {}
        if get_kv_dict(db, SCOPE_CONTACT_SOURCE, c.id) and _nonempty_blob(sj):
            n += 1
    if n:
        violations.append(("contacts: source_json nonempty while KV contact_source exists", n))

    n = 0
    for st in db.query(Step).order_by(Step.id.asc()).all():
        ij = st.input_json if isinstance(st.input_json, dict) else {}
        oj = st.output_json if isinstance(st.output_json, dict) else {}
        if get_kv_dict(db, SCOPE_STEP_INPUT, st.id) and _nonempty_blob(ij):
            n += 1
        if get_kv_dict(db, SCOPE_STEP_OUTPUT, st.id) and _nonempty_blob(oj):
            n += 1
    if n:
        violations.append(("steps: input_json/output_json nonempty while KV step_input/step_output exists", n))

    return violations


def main() -> int:
    db = SessionLocal()
    try:
        bad = audit(db)
    finally:
        db.close()

    if not bad:
        print("audit_json_residuals: OK — no duplicate legacy JSON blobs vs KV.")
        return 0

    print("audit_json_residuals: violations (run init_db / migrate_domain_json on this DB):", file=sys.stderr)
    for label, count in bad:
        print(f"  [{count}] {label}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
