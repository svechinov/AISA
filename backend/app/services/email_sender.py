import logging

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.config import settings
from app.repositories.email_draft_repo import (
    get_email_draft,
    list_sendable_email_drafts_by_run,
    mark_email_draft_failed,
    mark_email_draft_sent,
    mark_email_draft_sending,
)
from app.repositories.run_repo import get_run
from app.repositories.contact_repo import get_contact
from app.repositories.email_event_repo import create_email_event
from app.repositories.email_message_repo import create_email_message
from app.repositories.email_thread_repo import (
    create_email_thread,
    get_email_thread_by_draft_id,
    touch_email_thread,
)
from app.repositories.send_queue_repo import get_by_draft as get_send_queue_item_by_draft
from app.services.asset_attachment_service import (
    finalize_sendable_attachments,
    materialize_attachment,
    resolve_sendable_attachments_for_asset_ids,
)
from app.services.contact_gmail_history_service import mark_history_detected_after_outbound_send
from app.services.contactability import is_contactable
from app.services.email_provider import send_email_via_provider
from app.services.outbound_email_body import (
    append_additional_assets_section_to_email_html,
    append_signature_html_after,
    inline_images_for_email_html,
    normalize_draft_body_for_email_html,
    pick_signature_language,
)
from app.services.persona_service import ANASTASIA_SLUG, CAN_SPAM_ADDRESS_PLACEHOLDER, get_run_persona
from app.services.run_context_service import get_sender_signature_html
from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_email_draft

_log = logging.getLogger(__name__)


def _outreach_mime_attachments_and_exclude_ids(
    db: Session,
    raw_asset_ids: object,
) -> tuple[list[dict], frozenset[int]]:
    """CDN/local sendable assets as MIME payloads; their ids should not repeat as link-only rows."""
    ids = normalize_attached_asset_ids(raw_asset_ids)
    if not ids:
        return [], frozenset()
    sendable, link_only, skipped = resolve_sendable_attachments_for_asset_ids(db, ids)
    sendable = finalize_sendable_attachments(db, sendable, link_only, skipped)
    exclude = frozenset(
        int(m["asset_id"]) for m in sendable if m.get("asset_id") is not None
    )
    payloads: list[dict] = []
    for meta in sendable:
        data, fn, mt = materialize_attachment(meta)
        payloads.append({"filename": fn, "content": data, "mime_type": mt})
    return payloads, exclude


def validate_outbound_draft_sendable(db: Session, draft) -> None:
    """Raises ValueError if this draft row cannot be sent. The single chokepoint for send
    eligibility — used by the manual send endpoints, send_one_draft, AND evaluate_gates (queue
    worker), so a suppressed/dead recipient or a signature-less run can't leak out through
    whichever path forgot to check it. Temporal gates (caps/window/one-dialog-per-company) are
    worker-only and live in sending_gates.py, not here — a manual send is a deliberate override
    of scheduling, not of do-not-contact."""
    if draft.review_status not in {"approved", "edited"}:
        raise ValueError("Draft is not approved")

    if not (draft.to_email or "").strip():
        raise ValueError("Missing recipient email")

    if draft.status not in {"draft", "failed"}:
        raise ValueError("Draft is not sendable in current state")

    run = get_run(db, draft.run_id)
    if run and run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")
    if run and not (get_sender_signature_html(run) or "").strip():
        raise ValueError("Run has no sender signature configured — cannot send unsigned emails")

    # CAN-SPAM (B-128 Phase 1c): only personas whose signature template actually references the
    # postal-address placeholder are gated — Alexey's Cyprus signature has no placeholder, so his
    # live send is untouched. Stepan's (US track) does, so his run is held until Алексей supplies
    # the real address in CAN_SPAM_POSTAL_ADDRESS. Checked against the persona's raw signature
    # template (not the resolved run copy — get_sender_signature_html already substitutes it).
    if run:
        persona = get_run_persona(db, run)
        persona_sig = (getattr(persona, "signature_html", None) or "")
        if CAN_SPAM_ADDRESS_PLACEHOLDER in persona_sig and not (settings.CAN_SPAM_POSTAL_ADDRESS or "").strip():
            raise ValueError(
                "CAN-SPAM postal address not configured for this persona — cannot send until "
                "CAN_SPAM_POSTAL_ADDRESS is set"
            )

    contact = get_contact(db, draft.contact_id) if getattr(draft, "contact_id", None) else None
    contactable = is_contactable(db, draft.to_email, contact)
    if not contactable.ok:
        raise ValueError(contactable.reason)


def _resolve_send_mailbox(db: Session, draft, run) -> str | None:
    """Which mailbox to send this draft from (B-071 stage B): the send_queue item's mailbox_email
    when this draft was planned through the queue, else the run's persona primary mailbox. None
    when neither resolves — send_email_via_provider then falls back to the global mailbox."""
    item = get_send_queue_item_by_draft(db, draft.id)
    if item and (item.mailbox_email or "").strip():
        return item.mailbox_email.strip()
    persona = get_run_persona(db, run)
    mailbox = (getattr(persona, "primary_mailbox_email", None) or "").strip()
    return mailbox or None


def send_one_draft(db: Session, draft_id: int) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    validate_outbound_draft_sendable(db, draft)

    run = get_run(db, draft.run_id)
    persona = get_run_persona(db, run) if run else None
    anastasia_style = bool(persona and persona.slug == ANASTASIA_SLUG)
    base_raw = str(draft.body or "").strip()
    base = normalize_draft_body_for_email_html(draft.body, anastasia_style=anastasia_style) if base_raw else ""
    sig_html = get_sender_signature_html(run) if run else None
    has_sig = bool(str(sig_html or "").strip())

    try:
        eff_ids = effective_attached_asset_ids_for_email_draft(db, draft)
        attachment_payloads, mime_exclude_ids = _outreach_mime_attachments_and_exclude_ids(
            db,
            eff_ids,
        )
        base = append_additional_assets_section_to_email_html(
            base,
            db,
            eff_ids,
            trailing_rule_if_no_signature_below=not has_sig,
            exclude_asset_ids=mime_exclude_ids,
        )
        lang = pick_signature_language(draft.body, getattr(run.run_setup, "language", None) if run else None)
        body_out = append_signature_html_after(base, sig_html, language=lang)

        mark_email_draft_sending(db, draft)

        create_email_event(
            db=db,
            run_id=draft.run_id,
            draft_id=draft.id,
            contact_id=draft.contact_id,
            event_type="queued",
            payload_json={},
        )

        result = send_email_via_provider(
            to_email=draft.to_email.strip(),
            subject=draft.subject,
            body=body_out,
            attachments=attachment_payloads if attachment_payloads else None,
            db=db,
            mailbox_email=_resolve_send_mailbox(db, draft, run),
            inline_images=inline_images_for_email_html(body_out),
        )

        mark_email_draft_sent(
            db,
            draft,
            provider_message_id=result.get("provider_message_id"),
            thread_id=result.get("thread_id"),
        )

        create_email_event(
            db=db,
            run_id=draft.run_id,
            draft_id=draft.id,
            contact_id=draft.contact_id,
            event_type="sent",
            provider_message_id=result.get("provider_message_id"),
            payload_json=result,
        )

        draft = get_email_draft(db, draft.id)
        existing_thread = get_email_thread_by_draft_id(db, draft.id)
        thread = existing_thread
        if not thread:
            thread = create_email_thread(
                db=db,
                run_id=draft.run_id,
                contact_id=draft.contact_id,
                draft_id=draft.id,
                subject=draft.subject,
                provider_thread_id=result.get("thread_id"),
                status="open",
            )

        create_email_message(
            db=db,
            thread_id=thread.id,
            run_id=draft.run_id,
            contact_id=draft.contact_id,
            draft_id=draft.id,
            direction="outbound",
            from_email=None,
            to_email=draft.to_email,
            subject=draft.subject,
            body=body_out,
            provider_message_id=result.get("provider_message_id"),
            rfc_message_id=result.get("rfc_message_id"),
        )

        touch_email_thread(db, thread)

        if (result.get("provider") or "").strip().lower() == "gmail":
            try:
                mark_history_detected_after_outbound_send(db, draft.run_id, draft.to_email)
            except Exception:
                _log.exception(
                    "post-send: mark_history_detected_after_outbound_send (draft_id=%s)",
                    draft.id,
                )

        # Keep the send queue consistent whether this was the worker or a manual send.
        try:
            from app.repositories.send_queue_repo import mark_draft_queue_item_sent

            mark_draft_queue_item_sent(db, draft.id)
        except Exception:
            _log.exception("post-send: mark_draft_queue_item_sent (draft_id=%s)", draft.id)

        return {
            "draft_id": draft.id,
            "status": "sent",
            "provider_message_id": result.get("provider_message_id"),
        }

    except Exception as e:  # noqa: BLE001
        mark_email_draft_failed(db, draft, str(e))

        create_email_event(
            db=db,
            run_id=draft.run_id,
            draft_id=draft.id,
            contact_id=draft.contact_id,
            event_type="failed",
            error_message=str(e),
            payload_json={},
        )

        return {
            "draft_id": draft.id,
            "status": "failed",
            "error": str(e),
        }


def send_one_draft_in_thread(draft_id: int) -> None:
    """Runs send_one_draft in a worker thread with its own DB session (API returns 202 before this finishes)."""
    db = SessionLocal()
    try:
        send_one_draft(db, draft_id)
    except ValueError as e:
        _log.warning("send_one_draft (async) draft_id=%s: %s", draft_id, e)
    except Exception:
        _log.exception("send_one_draft (async) draft_id=%s", draft_id)
    finally:
        db.close()


def send_approved_drafts_for_run_in_thread(run_id: int) -> None:
    db = SessionLocal()
    try:
        send_approved_drafts_for_run(db, run_id)
    except ValueError as e:
        _log.warning("send_approved_drafts_for_run (async) run_id=%s: %s", run_id, e)
    except Exception:
        _log.exception("send_approved_drafts_for_run (async) run_id=%s", run_id)
    finally:
        db.close()


def send_approved_drafts_for_run(db: Session, run_id: int) -> dict:
    run = get_run(db, run_id)
    if run and run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")

    drafts = list_sendable_email_drafts_by_run(db, run_id)

    results = []
    for draft in drafts:
        results.append(send_one_draft(db, draft.id))

    return {
        "run_id": run_id,
        "attempted": len(drafts),
        "results": results,
    }



