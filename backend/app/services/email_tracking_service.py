from sqlalchemy.orm import Session

from app.repositories.contact_repo import (
    find_replacement_contact_for_source,
    get_contact,
    mark_contact_email_health,
    mark_contact_replied,
)
from app.repositories.email_draft_repo import (
    get_email_draft,
    mark_email_draft_bounced,
    mark_email_draft_dead_mailbox,
    mark_email_draft_replied,
)
from app.repositories.email_event_repo import create_email_event
from app.repositories.research_task_repo import create_research_task, find_pending_replacement_task
from app.services.outreach_notify import notify
from app.services.research_task_input import build_find_replacement_input_json


def register_replied_event(
    db: Session,
    draft_id: int,
    payload_json: dict | None = None,
    classification: str | None = None,
) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    if draft.tracking_status == "replied":
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": "replied",
            "skipped": True,
        }
    if draft.tracking_status in ("bounced", "dead_mailbox"):
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": draft.tracking_status,
            "skipped": True,
        }

    mark_email_draft_replied(db, draft)

    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_replied(db, contact)

    event = create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="replied",
        provider_message_id=draft.provider_message_id,
        payload_json=payload_json or {},
    )

    contact_ref = contact.email if contact else f"contact #{draft.contact_id}"
    # B-138: include the reply classification when the caller has one (real Gmail sync does).
    class_suffix = f" (класс: {classification})" if classification else ""
    notify(f"📩 Run #{draft.run_id}: ответ от {contact_ref}{class_suffix}")

    return {
        "draft_id": draft.id,
        "event_id": event.id,
        "status": "replied",
        "skipped": False,
    }


def register_bounced_event(
    db: Session,
    draft_id: int,
    payload_json: dict | None = None,
    error_message: str | None = None,
) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    if draft.tracking_status in ("bounced", "dead_mailbox"):
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": draft.tracking_status,
            "skipped": True,
        }
    if draft.tracking_status == "replied":
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": "replied",
            "skipped": True,
        }

    mark_email_draft_bounced(db, draft, error_message=error_message)

    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_email_health(db, contact, "bounced")

    event = create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="bounced",
        provider_message_id=draft.provider_message_id,
        payload_json=payload_json or {},
        error_message=error_message,
    )

    contact_ref = contact.email if contact else f"contact #{draft.contact_id}"
    reason = (error_message or "").strip()
    reason_suffix = f": {reason[:200]}" if reason else ""
    notify(f"↩️ Run #{draft.run_id}: bounce у {contact_ref}{reason_suffix}")

    return {
        "draft_id": draft.id,
        "event_id": event.id,
        "status": "bounced",
        "skipped": False,
    }


def register_dead_mailbox_event(
    db: Session,
    draft_id: int,
    payload_json: dict | None = None,
    error_message: str | None = None,
) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    if draft.tracking_status in ("dead_mailbox", "bounced"):
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": draft.tracking_status,
            "skipped": True,
        }
    if draft.tracking_status == "replied":
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": "replied",
            "skipped": True,
        }

    mark_email_draft_dead_mailbox(db, draft, error_message=error_message)

    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_email_health(db, contact, "dead_mailbox")

        replacement_exists = find_replacement_contact_for_source(db, draft.run_id, contact.id)
        if not find_pending_replacement_task(db, draft.run_id, contact.id) and not replacement_exists:
            create_research_task(
                db=db,
                run_id=draft.run_id,
                contact_id=contact.id,
                company=contact.company,
                task_type="find_replacement_email",
                status="open",
                reason="dead_mailbox",
                input_json=build_find_replacement_input_json(contact),
                output_json={},
            )

    event = create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="dead_mailbox",
        provider_message_id=draft.provider_message_id,
        payload_json=payload_json or {},
        error_message=error_message,
    )

    return {
        "draft_id": draft.id,
        "event_id": event.id,
        "status": "dead_mailbox",
        "skipped": False,
    }


def register_manual_bounce(
    db: Session,
    draft_id: int,
    *,
    payload_json: dict | None = None,
    error_message: str | None = None,
) -> dict:
    """
    Human override from UI / LLM: set bounced even if tracking was replied or other non-terminal state.
    Skips only if already bounced.
    """
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")
    if draft.tracking_status == "bounced":
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": "bounced",
            "skipped": True,
        }
    if draft.tracking_status == "dead_mailbox":
        raise ValueError("Already classified as dead mailbox — cannot mark as bounced.")

    mark_email_draft_bounced(db, draft, error_message=error_message)
    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_email_health(db, contact, "bounced")

    base_payload = dict(payload_json or {})
    event = create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="bounced",
        provider_message_id=draft.provider_message_id,
        payload_json=base_payload,
        error_message=error_message,
    )
    return {
        "draft_id": draft.id,
        "event_id": event.id,
        "status": "bounced",
        "skipped": False,
    }


def register_manual_dead_mailbox(
    db: Session,
    draft_id: int,
    *,
    payload_json: dict | None = None,
    error_message: str | None = None,
) -> dict:
    """
    Human override from UI / LLM: set dead_mailbox even if tracking was replied or bounced.
    Skips only if already dead_mailbox.
    """
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")
    if draft.tracking_status == "dead_mailbox":
        return {
            "draft_id": draft.id,
            "event_id": None,
            "status": "dead_mailbox",
            "skipped": True,
        }

    mark_email_draft_dead_mailbox(db, draft, error_message=error_message)
    contact = get_contact(db, draft.contact_id)
    if contact:
        mark_contact_email_health(db, contact, "dead_mailbox")
        replacement_exists = find_replacement_contact_for_source(db, draft.run_id, contact.id)
        if not find_pending_replacement_task(db, draft.run_id, contact.id) and not replacement_exists:
            create_research_task(
                db=db,
                run_id=draft.run_id,
                contact_id=contact.id,
                company=contact.company,
                task_type="find_replacement_email",
                status="open",
                reason="dead_mailbox",
                input_json=build_find_replacement_input_json(contact),
                output_json={},
            )

    base_payload = dict(payload_json or {})
    event = create_email_event(
        db=db,
        run_id=draft.run_id,
        draft_id=draft.id,
        contact_id=draft.contact_id,
        event_type="dead_mailbox",
        provider_message_id=draft.provider_message_id,
        payload_json=base_payload,
        error_message=error_message,
    )
    return {
        "draft_id": draft.id,
        "event_id": event.id,
        "status": "dead_mailbox",
        "skipped": False,
    }
