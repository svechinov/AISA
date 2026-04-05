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
from app.repositories.email_event_repo import create_email_event
from app.repositories.email_message_repo import create_email_message
from app.repositories.email_thread_repo import (
    create_email_thread,
    get_email_thread_by_draft_id,
    touch_email_thread,
)
from app.services.asset_attachment_service import (
    finalize_sendable_attachments,
    materialize_attachment,
    resolve_sendable_attachments_for_asset_ids,
)
from app.services.email_provider import send_email_via_provider
from app.services.gmail_oauth import (
    GmailOAuthError,
    refresh_access_token,
    resolve_outbound_from_mime,
)
from app.services.contact_gmail_history_service import mark_history_detected_after_outbound_send
from app.services.outbound_email_body import (
    append_additional_assets_section_to_email_html,
    append_signature_html_after,
    normalize_draft_body_for_email_html,
)
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
    """Raises ValueError if this draft row cannot be sent (same rules as send_one_draft)."""
    if draft.review_status not in {"approved", "edited"}:
        raise ValueError("Draft is not approved")

    if not (draft.to_email or "").strip():
        raise ValueError("Missing recipient email")

    if draft.status not in {"draft", "failed"}:
        raise ValueError("Draft is not sendable in current state")

    run = get_run(db, draft.run_id)
    if run and run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")


def send_one_draft(db: Session, draft_id: int) -> dict:
    draft = get_email_draft(db, draft_id)
    if not draft:
        raise ValueError(f"Draft {draft_id} not found")

    validate_outbound_draft_sendable(db, draft)

    run = get_run(db, draft.run_id)
    base_raw = str(draft.body or "").strip()
    base = normalize_draft_body_for_email_html(draft.body) if base_raw else ""
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
        body_out = append_signature_html_after(base, sig_html)

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


# =============================================================================
# MOCK_SEND_PREVIEW — temporary; delete this entire block + API route + UI button.
# =============================================================================
def mock_send_first_approved_draft_preview(db: Session, run_id: int) -> dict:
    """
    Sends the first sendable approved/edited draft (same ordering as bulk send) to the **sender**
    mailbox — To matches From (GMAIL_SEND_AS_EMAIL when valid in Send-as, else Gmail profile email).
    Does not update draft status or create email_events / threads / messages.
    """
    run = get_run(db, run_id)
    if not run:
        raise ValueError("Run not found")
    if run.closed_at is not None:
        raise ValueError("Run is closed — cannot send new outreach")

    drafts = list_sendable_email_drafts_by_run(db, run_id)
    if not drafts:
        raise ValueError("No approved sendable drafts for this run")

    draft = drafts[0]
    base_raw = str(draft.body or "").strip()
    base = normalize_draft_body_for_email_html(draft.body) if base_raw else ""
    sig_html = get_sender_signature_html(run)
    has_sig = bool(str(sig_html or "").strip())
    eff_ids = effective_attached_asset_ids_for_email_draft(db, draft)
    preview_attachment_payloads, preview_mime_exclude = _outreach_mime_attachments_and_exclude_ids(
        db,
        eff_ids,
    )
    base = append_additional_assets_section_to_email_html(
        base,
        db,
        eff_ids,
        trailing_rule_if_no_signature_below=not has_sig,
        exclude_asset_ids=preview_mime_exclude,
    )
    body_out = append_signature_html_after(base, sig_html)
    try:
        access = refresh_access_token()
        _, preview_to = resolve_outbound_from_mime(access)
    except GmailOAuthError as e:
        raise ValueError(
            "Test send needs working Gmail OAuth and a valid From address "
            "(GMAIL_SEND_AS_EMAIL must be in «Send mail as» when set). "
            f"{e}",
        ) from e
    preview_to = (preview_to or "").strip()
    if not preview_to or "@" not in preview_to:
        raise ValueError("Could not resolve sender email for test send.")
    result = send_email_via_provider(
        to_email=preview_to,
        subject=draft.subject or "",
        body=body_out,
        attachments=preview_attachment_payloads if preview_attachment_payloads else None,
    )
    if (result.get("provider") or "").strip().lower() != "gmail":
        raise ValueError(
            "Preview send did not use real Gmail (API is in mock mode). No message left this server. "
            "Ensure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN are loaded in this process "
            "(GET /setup/status → gmail_send_ready), then recreate the backend container if you use Docker.",
        )
    return {
        "ok": True,
        "draft_id": draft.id,
        "original_to": (draft.to_email or "").strip(),
        "preview_sent_to": preview_to,
        "from_email": str(result.get("from_email") or ""),
        "subject": str(draft.subject or ""),
        "provider": str(result.get("provider") or ""),
        "provider_message_id": result.get("provider_message_id"),
    }


# =============================================================================
# end MOCK_SEND_PREVIEW
# =============================================================================
