"""Rule-based personalization payload for outreach (stage 1: grounded facts only, no LLM)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import engine
from app.models.contact import Contact
from app.repositories.project_repo import get_project
from app.repositories.run_repo import get_run
from app.services.run_context_service import get_effective_context
from app.utils.contact_personalization_io import save_personalization_dict
from app.utils.contact_source_payload import effective_contact_source_json

logger = logging.getLogger(__name__)

# Keys we may copy verbatim from source_json when present (no invention).
_SOURCE_JSON_FACT_KEYS = (
    "description",
    "summary",
    "about",
    "industry",
    "snippet",
    "company_description",
    "bio",
    "notes",
)


def _coalesce_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return s


def _truncate(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _facts_from_source_json(source_json: dict | None) -> list[str]:
    if not isinstance(source_json, dict):
        return []
    out: list[str] = []
    for key in _SOURCE_JSON_FACT_KEYS:
        v = source_json.get(key)
        if isinstance(v, str) and v.strip():
            out.append(_truncate(v, 400))
        if len(out) >= 3:
            break
    return out


def _base_facts(contact: Contact, source_json: dict | None) -> list[str]:
    facts: list[str] = []
    company = _coalesce_str(contact.company)
    if company:
        facts.append(f"Named organization: {company}.")
    website = _coalesce_str(contact.website)
    if website:
        facts.append(f"Listed site: {website}.")
    name = _coalesce_str(contact.name)
    role = _coalesce_str(contact.role) or _role_from_source_json(source_json or {})
    if name and role:
        facts.append(f"Contact: {name} ({role}).")
    elif name:
        facts.append(f"Contact name: {name}.")
    elif role:
        facts.append(f"Role/title: {role}.")
    return facts


def _role_from_source_json(sj: dict) -> str:
    for k in ("role", "title", "job_title", "position"):
        v = sj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def build_personalization(
    db: Session,
    contact: Contact,
    run: Any | None,
    project: Any | None,
) -> dict[str, Any]:
    """
    Build personalization payload for a contact. Uses only DB fields + source strings
    (no web fetch, no LLM). Requires contact.id when using relational source_kv.
    """
    sj: dict[str, Any] = {}
    if getattr(contact, "id", None) is not None:
        sj = effective_contact_source_json(db, contact)
    else:
        sj = dict(contact.source_json or {})
    ctx = get_effective_context(run) if run else {}
    offer = _coalesce_str(ctx.get("offer"))
    goal = _coalesce_str(ctx.get("goal"))
    target_entities = _coalesce_str(ctx.get("target_entities"))
    target_roles = _coalesce_str(ctx.get("target_roles"))
    tone = _coalesce_str(ctx.get("tone")) or "Professional"
    notes = _coalesce_str(ctx.get("notes"))

    company = _coalesce_str(contact.company)
    role = _coalesce_str(contact.role) or _role_from_source_json(sj)
    proj_name = _coalesce_str(getattr(project, "name", None)) if project else ""

    company_facts: list[str] = []
    seen: set[str] = set()
    for fact in _base_facts(contact, sj):
        key = fact.lower()
        if key not in seen:
            seen.add(key)
            company_facts.append(fact)
    for fact in _facts_from_source_json(sj):
        key = fact.lower()
        if key not in seen:
            seen.add(key)
            company_facts.append(fact)
    company_facts = company_facts[:5]

    if target_roles and role:
        role_angle = (
            f"Outreach targets roles like yours ({target_roles[:280]}); your stated role is {role}."
        )
    elif role:
        role_angle = f"The addressee is in a {role} capacity — align the ask with that responsibility."
    elif target_roles:
        role_angle = f"Campaign focuses on: {target_roles[:320]}."
    else:
        role_angle = "Align the message with the recipient’s stated role and organization."

    why_parts: list[str] = []
    if company:
        why_parts.append(f"{company} fits the campaign’s target profile.")
    if target_entities and company:
        why_parts.append(f"It relates to the defined target space ({target_entities[:200]}).")
    elif target_entities:
        why_parts.append(f"Target focus: {target_entities[:280]}.")
    if goal:
        why_parts.append(f"Campaign goal: {goal[:320]}.")
    if proj_name:
        why_parts.append(f"Project: {proj_name}.")
    why_this_company = " ".join(why_parts) if why_parts else (
        "Selected for this wave because the row matches the run’s outreach criteria."
    )

    if offer and company:
        offer_fit = f"The stated offer ({offer[:400]}) is framed for organizations like {company}."
    elif offer:
        offer_fit = f"Offer summary: {offer[:500]}."
    else:
        offer_fit = "Map the run’s offer from the brief to this recipient’s context when drafting."

    risks: list[str] = []
    if notes:
        risks.append(_truncate(notes, 500))
    if tone.lower() not in ("professional", ""):
        risks.append(f"Tone preference from brief: {tone}.")
    risks_or_constraints = " ".join(risks) if risks else ""

    return {
        "company_facts": company_facts,
        "role_angle": _truncate(role_angle, 1200),
        "why_this_company": _truncate(why_this_company, 1200),
        "offer_fit": _truncate(offer_fit, 1200),
        "risks_or_constraints": _truncate(risks_or_constraints, 1200),
    }


def sync_contact_personalization_row(db: Session, contact: Contact) -> None:
    """Recompute and persist contact_personalization (+ facts); clears legacy personalization_json."""
    run = get_run(db, contact.run_id)
    project = get_project(db, run.project_id) if run else None
    d = build_personalization(db, contact, run, project)
    if contact.id is None:
        contact.personalization_json = d
        return
    save_personalization_dict(db, contact.id, d)
    contact.personalization_json = {}


def resync_personalization_for_run(db: Session, run_id: int) -> int:
    """Recompute personalization for all contacts in a run (e.g. after outreach brief changes). Returns count."""
    rows = db.query(Contact).filter(Contact.run_id == run_id).order_by(Contact.id.asc()).all()
    for c in rows:
        sync_contact_personalization_row(db, c)
        db.add(c)
    db.commit()
    return len(rows)


def _ids_needing_personalization_backfill_sql():
    """Rows needing first-time backfill: empty legacy JSON and no relational row yet.

    After ``sync_contact_personalization_row``, ``personalization_json`` is cleared to ``{}`` while
    facts live in ``contact_personalization`` — the old predicate ``personalization_json = '{}'`` alone
    would match forever and deadlock ``ensure_schema`` (infinite while-loop in backfill).
    """
    dialect = engine.dialect.name
    if dialect == "postgresql":
        return text(
            """
            SELECT c.id FROM contacts c
            WHERE (c.personalization_json IS NULL
               OR c.personalization_json = CAST('{}' AS jsonb))
              AND NOT EXISTS (
                SELECT 1 FROM contact_personalization cp WHERE cp.contact_id = c.id
              )
            ORDER BY c.id
            LIMIT :lim
            """
        )
    # SQLite (and generic): JSON stored as TEXT
    return text(
        """
        SELECT c.id FROM contacts c
        WHERE (c.personalization_json IS NULL
           OR c.personalization_json = '{}')
          AND NOT EXISTS (
            SELECT 1 FROM contact_personalization cp WHERE cp.contact_id = c.id
          )
        ORDER BY c.id
        LIMIT :lim
        """
    )


def backfill_empty_personalization_json(db: Session, *, batch_size: int = 500) -> int:
    """
    Fill personalization_json for contacts that still have NULL or empty {} (e.g. existing rows
    after migration). Idempotent: does nothing when no rows match. Uses run/project caches per batch.
    """
    total = 0
    run_cache: dict[int, Any] = {}
    proj_cache: dict[int, Any] = {}

    def _cached_run(rid: int) -> Any:
        if rid not in run_cache:
            run_cache[rid] = get_run(db, rid)
        return run_cache[rid]

    def _cached_proj(pid: int) -> Any:
        if pid not in proj_cache:
            proj_cache[pid] = get_project(db, pid)
        return proj_cache[pid]

    stmt = _ids_needing_personalization_backfill_sql()
    while True:
        rows = db.execute(stmt, {"lim": batch_size}).fetchall()
        if not rows:
            break
        ids = [r[0] for r in rows]
        contacts = db.query(Contact).filter(Contact.id.in_(ids)).order_by(Contact.id.asc()).all()
        for c in contacts:
            run = _cached_run(c.run_id)
            proj = _cached_proj(run.project_id) if run else None
            sync_contact_personalization_row(db, c)
            db.add(c)
        db.commit()
        total += len(contacts)
        if len(ids) < batch_size:
            break
    if total:
        logger.info("Backfilled personalization_json for %s contact(s).", total)
    return total
