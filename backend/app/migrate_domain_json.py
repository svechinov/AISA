"""Startup migration: move legacy JSON blob columns into relational tables + entity_json_kv."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import (
    SCOPE_ASSET_METADATA,
    SCOPE_ASSET_PACKET,
    SCOPE_CONTACT_SOURCE,
    SCOPE_FOLLOW_UP_OUTPUT,
    SCOPE_FOLLOW_UP_SOURCE,
    SCOPE_RESEARCH_INPUT,
    SCOPE_RESEARCH_OUTPUT,
    SCOPE_RUN_COMPANY_EXTRA,
    SCOPE_STEP_INPUT,
    SCOPE_STEP_OUTPUT,
)
from app.models.asset import Asset
from app.models.asset_packet import AssetPacket
from app.models.contact import Contact
from app.models.contact_personalization import ContactPersonalization
from app.models.follow_up_task import FollowUpTask
from app.models.research_task import ResearchTask
from app.models.run import Run
from app.models.run_company import RunCompany
from app.models.run_master_email_variant import RunMasterEmailVariant
from app.models.step import Step
from app.models.template import Template
from app.models.template_variable import TemplateVariable
from app.utils.contact_personalization_io import save_personalization_dict
from app.utils.entity_kv_storage import get_kv_dict, replace_kv_dict
from app.utils.follow_up_task_payload import persist_follow_up_output, persist_follow_up_source
from app.utils.research_task_payload import persist_research_input, persist_research_output
from app.utils.run_relational_payload import (
    inner_from_context_json_blob,
    persist_run_context_extras_from_blob,
    persist_run_input_from_blob,
    replace_master_email_variants,
    upsert_run_outreach_context_row,
)
from app.utils.step_payload import persist_step_input, persist_step_output
from app.utils.template_variables_io import replace_template_variables_from_dict

logger = logging.getLogger(__name__)


def migrate_domain_json_to_relational(db: Session) -> None:
    """Idempotent: copies non-empty legacy JSON into new storage, then clears blobs."""
    touched = {"runs": 0, "steps": 0, "contacts": 0, "templates": 0, "assets": 0, "packets": 0, "run_companies": 0}

    for run in db.query(Run).order_by(Run.id.asc()).all():
        changed = False
        ctx = dict(run.context_json or {})
        if ctx:
            inner = inner_from_context_json_blob(ctx)
            upsert_run_outreach_context_row(db, run.id, inner)
            persist_run_context_extras_from_blob(db, run.id, ctx)
            run.context_json = {}
            changed = True
        ij = dict(run.input_json or {})
        if ij:
            persist_run_input_from_blob(db, run, ij)
            run.input_json = {}
            changed = True
        me = getattr(run, "master_email", None)
        has_variants = (
            db.query(RunMasterEmailVariant).filter(RunMasterEmailVariant.run_id == run.id).first() is not None
        )
        if isinstance(me, dict) and me.get("variants") and not has_variants:
            vlist = me.get("variants")
            if isinstance(vlist, list) and vlist:
                replace_master_email_variants(
                    db,
                    run.id,
                    [
                        {"subject": str(x.get("subject") or ""), "body": str(x.get("body") or "")}
                        for x in vlist
                        if isinstance(x, dict)
                    ],
                )
            run.master_email = None
            changed = True
        elif isinstance(me, dict) and me and has_variants:
            run.master_email = None
            changed = True
        if changed:
            db.add(run)
            touched["runs"] += 1

    for st in db.query(Step).order_by(Step.id.asc()).all():
        if not get_kv_dict(db, SCOPE_STEP_INPUT, st.id):
            ij = dict(st.input_json or {})
            if ij:
                persist_step_input(db, st, ij)
                touched["steps"] += 1
        if not get_kv_dict(db, SCOPE_STEP_OUTPUT, st.id):
            oj = dict(st.output_json or {})
            if oj:
                persist_step_output(db, st, oj)
                touched["steps"] += 1

    for c in db.query(Contact).order_by(Contact.id.asc()).all():
        if not get_kv_dict(db, SCOPE_CONTACT_SOURCE, c.id):
            sj = dict(c.source_json or {})
            if sj:
                replace_kv_dict(db, SCOPE_CONTACT_SOURCE, c.id, sj)
                c.source_json = {}
                touched["contacts"] += 1
        pj = dict(c.personalization_json or {})
        if pj and not db.query(ContactPersonalization).filter(ContactPersonalization.contact_id == c.id).first():
            save_personalization_dict(db, c.id, pj)
            c.personalization_json = {}
            touched["contacts"] += 1

    for t in db.query(Template).order_by(Template.id.asc()).all():
        vj = dict(t.variables_json or {})
        if not vj:
            continue
        if db.query(TemplateVariable).filter(TemplateVariable.template_id == t.id).first():
            continue
        replace_template_variables_from_dict(db, t.id, vj)
        t.variables_json = {}
        db.add(t)
        touched["templates"] += 1

    for a in db.query(Asset).order_by(Asset.id.asc()).all():
        mj = dict(a.metadata_json or {})
        if mj and not get_kv_dict(db, SCOPE_ASSET_METADATA, a.id):
            replace_kv_dict(db, SCOPE_ASSET_METADATA, a.id, mj)
            a.metadata_json = {}
            db.add(a)
            touched["assets"] += 1
    for p in db.query(AssetPacket).order_by(AssetPacket.id.asc()).all():
        pj = dict(p.packet_json or {})
        if pj and not get_kv_dict(db, SCOPE_ASSET_PACKET, p.id):
            # Do not copy assets into KV — junction table is canonical after backfill in init_db.
            clean = {k: v for k, v in pj.items() if k != "assets"}
            replace_kv_dict(db, SCOPE_ASSET_PACKET, p.id, clean if clean else None)
            touched["packets"] += 1
    for rc in db.query(RunCompany).order_by(RunCompany.id.asc()).all():
        ej = dict(rc.extra_json or {})
        if ej and not get_kv_dict(db, SCOPE_RUN_COMPANY_EXTRA, rc.id):
            replace_kv_dict(db, SCOPE_RUN_COMPANY_EXTRA, rc.id, ej)
            rc.extra_json = {}
            db.add(rc)
            touched["run_companies"] += 1

    for ft in db.query(FollowUpTask).order_by(FollowUpTask.id.asc()).all():
        if not get_kv_dict(db, SCOPE_FOLLOW_UP_SOURCE, ft.id):
            sj = dict(ft.source_json or {})
            if sj:
                persist_follow_up_source(db, ft, sj)
        if not get_kv_dict(db, SCOPE_FOLLOW_UP_OUTPUT, ft.id):
            oj = dict(ft.output_json or {})
            if oj:
                persist_follow_up_output(db, ft, oj)
    for rt in db.query(ResearchTask).order_by(ResearchTask.id.asc()).all():
        if not get_kv_dict(db, SCOPE_RESEARCH_INPUT, rt.id):
            ij = dict(rt.input_json or {})
            if ij:
                persist_research_input(db, rt, ij)
        if not get_kv_dict(db, SCOPE_RESEARCH_OUTPUT, rt.id):
            oj = dict(rt.output_json or {})
            if oj:
                persist_research_output(db, rt, oj)

    db.commit()
    if any(touched.values()):
        logger.info("domain JSON migration: %s", touched)
