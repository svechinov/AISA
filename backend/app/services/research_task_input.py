"""Shared payload for find_replacement_email tasks (manual + tracking)."""

from app.models.contact import Contact


def build_find_replacement_input_json(contact: Contact) -> dict:
    return {
        "company": contact.company,
        "website": contact.website,
        "previous_contact": {
            "name": contact.name,
            "role": contact.role,
            "email": contact.email,
        },
        "previous_email": contact.email,
        "previous_role": contact.role,
        "search_constraints": {
            "preferred_roles": [
                "Content Acquisition",
                "Content Partnerships",
                "Acquisitions",
                "Content Licensing",
            ],
            "exclude_emails": [contact.email] if contact.email else [],
        },
    }
