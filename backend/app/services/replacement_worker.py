"""Mock replacement search — no DB writes; real enrichment plugs in later."""

from sqlalchemy.orm import Session

from app.models.research_task import ResearchTask
from app.repositories.contact_repo import get_contact


def find_replacement_candidate(db: Session, task: ResearchTask) -> dict | None:
    """
    Mock logic. Later: real enrichment/search.
    Returns a candidate dict or None (caller marks task no_result).
    """
    old_contact = get_contact(db, task.contact_id) if task.contact_id else None
    if not old_contact and not task.company:
        return None

    company = task.company or (old_contact.company if old_contact else None)
    inp = task.input_json or {}
    website = inp.get("website") or (old_contact.website if old_contact else None)
    old_email = (
        (inp.get("previous_email") or (old_contact.email if old_contact else "") or "")
        .strip()
        .lower()
    )

    domain = ""
    if website:
        domain = (
            website.replace("https://", "")
            .replace("http://", "")
            .replace("www.", "")
            .split("/")[0]
            .strip()
        )

    if not domain:
        return None

    replacement_email = f"partnerships@{domain}"
    if replacement_email == old_email:
        replacement_email = f"acquisitions@{domain}"

    return {
        "company": company,
        "website": website,
        "name": "Replacement Contact",
        "role": "Content Partnerships",
        "email": replacement_email,
        "linkedin": None,
        "confidence": "medium",
    }
