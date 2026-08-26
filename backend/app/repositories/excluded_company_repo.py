"""Cross-run company exclusion registry (B-264) — the company-level twin of suppression_list."""

from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.excluded_company import EXCLUDE_REASON_MANUAL, ExcludedCompany


def company_name_key(name: str | None) -> str | None:
    """Canonical match key for a company name: lowercase, letters/digits only.

    "8Bit Recruitment Ltd." and "8bit recruitment ltd" collapse to one key; different companies with
    genuinely different names never do. Corporate suffixes are deliberately KEPT — dropping them
    would merge "Sunday Games" and "Sunday Games Studio", which can be different studios."""
    key = re.sub(r"[^a-z0-9а-яё]", "", (name or "").lower())
    return key or None


def domain_key(website: str | None) -> str | None:
    """Bare registrable host from a website URL ('https://www.8bit.io/careers' -> '8bit.io')."""
    from app.services.apollo_service import domain_from_website

    return domain_from_website(website or "") or None


def is_company_excluded(db: Session, name: str | None, website: str | None) -> ExcludedCompany | None:
    """The registry row that excludes this company, or None. Domain match wins; the name key is the
    fallback for rows collected without a usable website."""
    dom = domain_key(website)
    key = company_name_key(name)
    if not dom and not key:
        return None
    conditions = []
    if dom:
        conditions.append(ExcludedCompany.domain == dom)
    if key:
        conditions.append(ExcludedCompany.name_key == key)
    return db.query(ExcludedCompany).filter(or_(*conditions)).first()


def add_excluded_company(
    db: Session,
    name: str | None,
    website: str | None = None,
    reason: str = EXCLUDE_REASON_MANUAL,
    note: str | None = None,
    source_run_id: int | None = None,
) -> ExcludedCompany | None:
    """Idempotent upsert by domain/name key. Returns the row (existing or new); None when the
    company has neither a usable domain nor a usable name."""
    dom = domain_key(website)
    key = company_name_key(name)
    if not dom and not key:
        return None
    existing = is_company_excluded(db, name, website)
    if existing is not None:
        # Fill in an identity the earlier row was missing (e.g. added by name, seen later with a
        # website) so the next sweep matches on either.
        changed = False
        if dom and not existing.domain:
            existing.domain = dom
            changed = True
        if key and not existing.name_key:
            existing.name_key = key
            changed = True
        if changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing
    row = ExcludedCompany(
        domain=dom,
        name_key=key,
        name=(name or "").strip() or None,
        reason=reason,
        note=note,
        source_run_id=source_run_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_excluded_companies(db: Session, limit: int = 500) -> list[ExcludedCompany]:
    return (
        db.query(ExcludedCompany)
        .order_by(ExcludedCompany.created_at.desc())
        .limit(limit)
        .all()
    )


def count_excluded_companies(db: Session) -> int:
    return db.query(ExcludedCompany.id).count()


def delete_excluded_company(db: Session, entry_id: int) -> bool:
    """Remove an exclusion (a wrongly-excluded company). Returns False if the id doesn't exist."""
    row = db.query(ExcludedCompany).filter(ExcludedCompany.id == entry_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def filter_excluded_companies(
    db: Session, companies: list[dict], *, run_id: int | None = None
) -> tuple[list[dict], list[tuple[dict, ExcludedCompany]]]:
    """Split a freshly collected company list into (kept, dropped) using the registry.

    Dropped rows carry the registry entry that excluded them, so the caller can tell the user WHY a
    company disappeared instead of silently shrinking the wave."""
    kept: list[dict] = []
    dropped: list[tuple[dict, ExcludedCompany]] = []
    for c in companies:
        if not isinstance(c, dict):
            continue
        hit = is_company_excluded(db, str(c.get("name") or ""), str(c.get("website") or ""))
        if hit is not None:
            dropped.append((c, hit))
        else:
            kept.append(c)
    return kept, dropped
