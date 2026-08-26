from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.reply_draft import ReplyDraft
from app.repositories.asset_packet_repo import get_packet_by_reply_draft_id
from app.repositories.email_attachment_repo import create_email_attachment
from app.repositories.email_event_repo import create_email_event
from app.repositories.email_message_repo import create_email_message
from app.repositories.email_thread_repo import get_email_thread, touch_email_thread
from app.repositories.run_repo import get_run
from app.repositories.reply_draft_repo import (
    get_reply_draft,
    mark_reply_draft_failed,
    mark_reply_draft_sent,
    mark_reply_draft_sending,
)
from app.repositories.send_queue_repo import get_by_draft as get_send_queue_item_by_draft
from app.utils.attached_asset_ids import normalize_attached_asset_ids
from app.utils.draft_attached_assets import effective_attached_asset_ids_for_reply_draft
from app.services.asset_attachment_service import (
    finalize_sendable_attachments,
    materialize_attachment,
    resolve_sendable_attachments_for_asset_ids,
)
from app.services.asset_packet_service import (
    get_ordered_asset_refs_for_packet,
    lock_packet_after_send,
    render_assets_block_for_email,
)

from app.services.contact_gmail_history_service import mark_history_detected_after_outbound_send
from app.services.email_provider import send_email_via_provider
from app.services.outbound_email_body import (
    append_additional_assets_section_to_email_html,
    append_signature_html_after,
    inline_images_for_email_html,
    normalize_draft_body_for_email_html,
    pick_signature_language,
)
from app.services.persona_service import ANASTASIA_SLUG, get_run_persona
from app.services.run_context_service import get_sender_signature_html

logger = logging.getLogger(__name__)


def validate_packet_for_reply_send(reply_draft: ReplyDraft, packet) -> None:
    if not packet:
        return

    if packet.status == "archived":
        raise ValueError("Attached packet is archived")

    if packet.run_id != reply_draft.run_id:
        raise ValueError("Attached packet run_id mismatch")

    if packet.thread_id is not None and packet.thread_id != reply_draft.thread_id:
        raise ValueError("Attached packet thread_id mismatch")

    if packet.contact_id and reply_draft.contact_id and packet.contact_id != reply_draft.contact_id:
        raise ValueError("Attached packet contact_id mismatch")


def _combine_body(base_body: str, packet_block: str) -> str:
    if not packet_block.strip():
        return base_body
    if base_body.endswith("\n"):
        return f"{base_body}{packet_block}"
    return f"{base_body}\n{packet_block}"


def _public_attachment_candidate(meta: dict) -> dict:
    return {
        "asset_id": meta["asset_id"],
        "filename": meta["filename"],
        "mime_type": meta["mime_type"],
        "source_kind": "file" if meta.get("local_path") else "url",
    }


def build_reply_send_payload(db: Session, reply_draft: ReplyDraft) -> dict:
    base_body = reply_draft.body or ""
    packet = get_packet_by_reply_draft_id(db, reply_draft.id)
    validate_packet_for_reply_send(reply_draft, packet)

    run = get_run(db, reply_draft.run_id)
    persona = get_run_persona(db, run) if run else None
    anastasia_style = bool(persona and persona.slug == ANASTASIA_SLUG)
    sig_html = get_sender_signature_html(run) if run else None
    lang = pick_signature_language(base_body, getattr(run.run_setup, "language", None) if run else None)

    eff_reply_ids = effective_attached_asset_ids_for_reply_draft(db, reply_draft)
    draft_ids = normalize_attached_asset_ids(eff_reply_ids)
    packet_ids: list[int] = []
    if packet:
        for ref in get_ordered_asset_refs_for_packet(db, packet):
            if not isinstance(ref, dict) or ref.get("asset_id") is None:
                continue
            try:
                packet_ids.append(int(ref["asset_id"]))
            except (TypeError, ValueError):
                continue

    seen: set[int] = set()
    merged: list[int] = []
    for i in draft_ids:
        if i not in seen:
            seen.add(i)
            merged.append(i)
    for i in packet_ids:
        if i not in seen:
            seen.add(i)
            merged.append(i)

    if not merged:
        br = str(base_body or "").strip()
        base = normalize_draft_body_for_email_html(base_body, anastasia_style=anastasia_style) if br else ""
        has_sig = bool(str(sig_html or "").strip())
        base = append_additional_assets_section_to_email_html(
            base,
            db,
            eff_reply_ids,
            trailing_rule_if_no_signature_below=not has_sig,
        )
        final_body = append_signature_html_after(base, sig_html, language=lang)
        return {
            "base_body": base_body,
            "final_body": final_body,
            "attachments": [],
            "attachment_candidates": [],
            "real_attachments": [],
            "attached_asset_ids": [],
            "linked_asset_ids": [],
            "link_only_assets": [],
            "packet_block": "",
            "attached_packet_id": packet.id if packet else None,
            "skipped_attachments": [],
            "inline_images": inline_images_for_email_html(final_body),
        }

    sendable, link_only, skipped = resolve_sendable_attachments_for_asset_ids(db, merged)
    sendable = finalize_sendable_attachments(db, sendable, link_only, skipped)
    mime_exclude = frozenset(
        int(m["asset_id"]) for m in sendable if m.get("asset_id") is not None
    )
    packet_block = render_assets_block_for_email(link_only)
    combined = _combine_body(base_body, packet_block)
    cr = str(combined or "").strip()
    base = normalize_draft_body_for_email_html(combined, anastasia_style=anastasia_style) if cr else ""
    has_sig = bool(str(sig_html or "").strip())
    base = append_additional_assets_section_to_email_html(
        base,
        db,
        eff_reply_ids,
        trailing_rule_if_no_signature_below=not has_sig,
        exclude_asset_ids=mime_exclude,
    )
    final_body = append_signature_html_after(base, sig_html, language=lang)

    public_candidates = [_public_attachment_candidate(m) for m in sendable]
    real_attachments = [
        {"asset_id": m["asset_id"], "filename": m["filename"], "mime_type": m["mime_type"]}
        for m in sendable
    ]
    linked_asset_ids = []
    for row in link_only:
        if isinstance(row, dict) and row.get("asset_id") is not None:
            linked_asset_ids.append(int(row["asset_id"]))

    return {
        "base_body": base_body,
        "final_body": final_body,
        "attachments": sendable,
        "attachment_candidates": public_candidates,
        "real_attachments": real_attachments,
        "attached_asset_ids": [m["asset_id"] for m in sendable],
        "linked_asset_ids": linked_asset_ids,
        "link_only_assets": link_only,
        "packet_block": packet_block,
        "attached_packet_id": packet.id if packet else None,
        "skipped_attachments": skipped,
        "inline_images": inline_images_for_email_html(final_body),
    }


def build_final_reply_body(db: Session, reply_draft: ReplyDraft) -> str:
    return build_reply_send_payload(db, reply_draft)["final_body"]


def _resolve_reply_mailbox(db: Session, thread, run) -> str | None:
    """A reply must go out from the same mailbox as the original outbound send (B-071 stage B):
    the original draft's send_queue mailbox_email when known, else the run's persona primary
    mailbox. None when neither resolves — send_email_via_provider then falls back to the global
    mailbox (Alexey), same as before this stage."""
    if thread.draft_id:
        item = get_send_queue_item_by_draft(db, thread.draft_id)
        if item and (item.mailbox_email or "").strip():
            return item.mailbox_email.strip()
    persona = get_run_persona(db, run)
    mailbox = (getattr(persona, "primary_mailbox_email", None) or "").strip()
    return mailbox or None


def send_one_reply_draft(db: Session, draft_id: int) -> dict:
    draft = get_reply_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Reply draft {draft_id} not found")

    if draft.review_status not in {"approved", "edited"}:
        raise ValueError("Reply draft is not approved")

    if draft.status not in {"draft", "failed"}:
        raise ValueError("Reply draft is not sendable in current state")

    if not (draft.to_email or "").strip():
        raise ValueError("Missing recipient email on reply draft")

    thread = get_email_thread(db, draft.thread_id)
    if not thread:
        raise ValueError(f"Thread {draft.thread_id} not found")

    mark_reply_draft_sending(db, draft)

    try:
        payload = build_reply_send_payload(db, draft)
        final_body = payload["final_body"]
        attachment_payloads: list[dict] = []
        for meta in payload["attachments"]:
            data, fn, mt = materialize_attachment(meta)
            attachment_payloads.append({"filename": fn, "content": data, "mime_type": mt})

        run = get_run(db, draft.run_id)
        result = send_email_via_provider(
            to_email=(draft.to_email or "").strip(),
            subject=draft.subject,
            body=final_body,
            attachments=attachment_payloads if attachment_payloads else None,
            db=db,
            mailbox_email=_resolve_reply_mailbox(db, thread, run),
            inline_images=payload.get("inline_images"),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "reply draft send failed before provider acceptance (reply_draft_id=%s)",
            draft_id,
        )
        mark_reply_draft_failed(db, draft, str(e))
        return {
            "reply_draft_id": draft.id,
            "status": "failed",
            "error": str(e),
        }

    draft = get_reply_draft(db, draft.id) or draft

    try:
        mark_reply_draft_sent(
            db=db,
            draft=draft,
            provider_message_id=result.get("provider_message_id"),
        )
    except Exception:
        logger.exception(
            "post-send persistence error: mark_reply_draft_sent (reply_draft_id=%s)",
            draft.id,
        )

    message = None
    try:
        message = create_email_message(
            db=db,
            thread_id=thread.id,
            run_id=draft.run_id,
            contact_id=draft.contact_id,
            draft_id=None,
            direction="outbound",
            from_email=None,
            to_email=draft.to_email,
            subject=draft.subject,
            body=final_body,
            provider_message_id=result.get("provider_message_id"),
            rfc_message_id=result.get("rfc_message_id"),
        )
    except Exception:
        logger.exception(
            "post-send persistence error: create_email_message (reply_draft_id=%s)",
            draft.id,
        )

    if message is not None:
        att_ids = result.get("attachment_ids") or []
        for i, meta in enumerate(payload["attachments"]):
            try:
                create_email_attachment(
                    db=db,
                    message_id=message.id,
                    asset_id=meta["asset_id"],
                    filename=meta["filename"],
                    mime_type=meta["mime_type"],
                    source_url=meta.get("source_url"),
                    source_path=meta.get("source_path"),
                    provider_attachment_id=att_ids[i] if i < len(att_ids) else None,
                    status="attached",
                    error=None,
                )
            except Exception:
                logger.exception(
                    "post-send persistence error: create_email_attachment "
                    "(reply_draft_id=%s, index=%s)",
                    draft.id,
                    i,
                )

    try:
        sent_packet = get_packet_by_reply_draft_id(db, draft.id)
        if sent_packet is not None and payload.get("attached_packet_id") == sent_packet.id:
            lock_packet_after_send(db, sent_packet.id)
    except ValueError:
        logger.exception(
            "post-send persistence error: packet lookup integrity (reply_draft_id=%s)",
            draft.id,
        )
    except Exception:
        logger.exception(
            "post-send persistence error: lock_packet_after_send (reply_draft_id=%s)",
            draft.id,
        )

    try:
        touch_email_thread(db, thread)
    except Exception:
        logger.exception(
            "post-send persistence error: touch_email_thread (reply_draft_id=%s)",
            draft.id,
        )

    try:
        if thread.draft_id is not None:
            create_email_event(
                db=db,
                run_id=draft.run_id,
                draft_id=thread.draft_id,
                contact_id=draft.contact_id,
                event_type="reply_sent",
                provider_message_id=result.get("provider_message_id"),
                payload_json={
                    "reply_draft_id": draft.id,
                    "thread_id": thread.id,
                    "attachment_count": len(attachment_payloads),
                    "attached_asset_ids": payload["attached_asset_ids"],
                },
            )
    except Exception:
        logger.exception(
            "post-send persistence error: create_email_event (reply_draft_id=%s)",
            draft.id,
        )

    if (result.get("provider") or "").strip().lower() == "gmail":
        try:
            mark_history_detected_after_outbound_send(db, draft.run_id, draft.to_email)
        except Exception:
            logger.exception(
                "post-send: mark_history_detected_after_outbound_send (reply_draft_id=%s)",
                draft.id,
            )

    return {
        "reply_draft_id": draft.id,
        "status": "sent",
        "provider_message_id": result.get("provider_message_id"),
    }
