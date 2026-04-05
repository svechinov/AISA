"""Contact personalization: relational row + facts (replaces personalization_json blob)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.contact_personalization import ContactPersonalization, ContactPersonalizationFact


def get_personalization_dict(db: Session, contact_id: int, legacy_json: dict | None) -> dict[str, Any]:
    row = db.query(ContactPersonalization).filter(ContactPersonalization.contact_id == contact_id).first()
    if row is None:
        return dict(legacy_json or {})
    facts = (
        db.query(ContactPersonalizationFact)
        .filter(ContactPersonalizationFact.contact_id == contact_id)
        .order_by(ContactPersonalizationFact.position.asc())
        .all()
    )
    return {
        "company_facts": [f.fact_text for f in facts],
        "role_angle": (row.role_angle or "").strip(),
        "why_this_company": (row.why_this_company or "").strip(),
        "offer_fit": (row.offer_fit or "").strip(),
        "risks_or_constraints": (row.risks_or_constraints or "").strip(),
    }


def save_personalization_dict(db: Session, contact_id: int, d: dict[str, Any]) -> None:
    row = db.query(ContactPersonalization).filter(ContactPersonalization.contact_id == contact_id).first()
    if row is None:
        row = ContactPersonalization(contact_id=contact_id)
        db.add(row)
    row.role_angle = str(d.get("role_angle") or "")
    row.why_this_company = str(d.get("why_this_company") or "")
    row.offer_fit = str(d.get("offer_fit") or "")
    row.risks_or_constraints = str(d.get("risks_or_constraints") or "")
    db.query(ContactPersonalizationFact).filter(ContactPersonalizationFact.contact_id == contact_id).delete(
        synchronize_session=False
    )
    for i, fact in enumerate(d.get("company_facts") or []):
        if isinstance(fact, str) and fact.strip():
            db.add(
                ContactPersonalizationFact(
                    contact_id=contact_id,
                    position=i,
                    fact_text=fact.strip()[:1200],
                )
            )
