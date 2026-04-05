"""Split email_events payload_json into typed columns; API merges columns + payload_json (extras only)."""

from __future__ import annotations

from typing import Any


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _coerce_positive_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _coerce_non_negative_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _normalize_attached_asset_ids(v: Any) -> list | None:
    if v is None:
        return None
    if not isinstance(v, list):
        return None
    out: list[int] = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def split_payload_for_storage(
    payload: dict | None,
    event_type: str,
    *,
    provider_message_id_row: str | None = None,
) -> tuple[dict[str, Any], dict]:
    """
    Returns (column_values, remainder dict for payload_json).
    Column keys match EmailEvent ORM attributes.
    """
    p = dict(payload or {})
    cols: dict[str, Any] = {}

    pm_row = provider_message_id_row
    if "provider_message_id" in p and pm_row is not None:
        if str(p.get("provider_message_id") or "") == str(pm_row):
            p.pop("provider_message_id", None)

    if "source" in p:
        cols["payload_source"] = _opt_str(p.get("source"))
        p.pop("source", None)

    if "gmail_message_id" in p:
        cols["gmail_message_id"] = _opt_str(p.get("gmail_message_id"))
        p.pop("gmail_message_id", None)

    if "notification_excerpt" in p:
        ne = p.get("notification_excerpt")
        cols["notification_excerpt"] = ne if isinstance(ne, str) else _opt_str(ne)
        p.pop("notification_excerpt", None)

    if "llm_reason" in p:
        lr = p.get("llm_reason")
        cols["llm_reason"] = lr if isinstance(lr, str) else _opt_str(lr)
        p.pop("llm_reason", None)

    if "llm_delivery_issue" in p:
        cols["llm_delivery_issue"] = _opt_str(p.get("llm_delivery_issue"))
        p.pop("llm_delivery_issue", None)

    if "reply_draft_id" in p:
        rid = _coerce_positive_int(p.get("reply_draft_id"))
        if rid is not None:
            cols["reply_draft_id"] = rid
        p.pop("reply_draft_id", None)

    if event_type == "replied":
        if "from_email" in p:
            cols["inbound_from_email"] = _opt_str(p.get("from_email"))
            p.pop("from_email", None)
        if "to_email" in p:
            cols["inbound_to_email"] = _opt_str(p.get("to_email"))
            p.pop("to_email", None)
        if "subject" in p:
            sj = p.get("subject")
            cols["inbound_subject"] = sj if isinstance(sj, str) else _opt_str(sj)
            p.pop("subject", None)

    if "thread_id" in p:
        tid = p.get("thread_id")
        if event_type == "sent":
            cols["send_provider_thread_id"] = _opt_str(tid)
            p.pop("thread_id", None)
        else:
            ref = _coerce_positive_int(tid)
            if ref is not None:
                cols["email_thread_id"] = ref
                p.pop("thread_id", None)
            else:
                st = _opt_str(tid)
                if st:
                    cols["send_provider_thread_id"] = st
                    p.pop("thread_id", None)

    if event_type == "sent":
        if "provider" in p:
            cols["send_provider"] = _opt_str(p.get("provider"))
            p.pop("provider", None)
        if "rfc_message_id" in p:
            cols["send_rfc_message_id"] = _opt_str(p.get("rfc_message_id"))
            p.pop("rfc_message_id", None)
        if "to_email" in p:
            cols["send_to_email"] = _opt_str(p.get("to_email"))
            p.pop("to_email", None)
        if "subject" in p:
            sj = p.get("subject")
            cols["send_subject"] = sj if isinstance(sj, str) else _opt_str(sj)
            p.pop("subject", None)
        if "from_email" in p:
            cols["send_from_email"] = _opt_str(p.get("from_email"))
            p.pop("from_email", None)
        if "attachment_count" in p:
            n = _coerce_non_negative_int(p.get("attachment_count"))
            if n is not None:
                cols["send_attachment_count"] = n
            p.pop("attachment_count", None)

    if event_type == "reply_sent":
        if "attachment_count" in p:
            n = _coerce_non_negative_int(p.get("attachment_count"))
            if n is not None:
                cols["reply_attachment_count"] = n
            p.pop("attachment_count", None)
        if "attached_asset_ids" in p:
            norm = _normalize_attached_asset_ids(p.get("attached_asset_ids"))
            if norm is not None:
                cols["reply_attached_asset_ids_json"] = norm
            p.pop("attached_asset_ids", None)

    return cols, p


def build_payload_from_columns(e: Any) -> dict:
    """Rebuild the legacy merged payload shape from ORM columns."""
    et = getattr(e, "event_type", "") or ""
    out: dict[str, Any] = {}

    ps = getattr(e, "payload_source", None)
    if ps:
        out["source"] = ps
    gmid = getattr(e, "gmail_message_id", None)
    if gmid:
        out["gmail_message_id"] = gmid
    nex = getattr(e, "notification_excerpt", None)
    if nex:
        out["notification_excerpt"] = nex

    lr = getattr(e, "llm_reason", None)
    if lr:
        out["llm_reason"] = lr
    ldi = getattr(e, "llm_delivery_issue", None)
    if ldi:
        out["llm_delivery_issue"] = ldi

    rd = getattr(e, "reply_draft_id", None)
    if rd is not None and et == "reply_sent":
        out["reply_draft_id"] = rd

    if et == "sent":
        pm = getattr(e, "provider_message_id", None)
        if pm:
            out["provider_message_id"] = pm
        sp = getattr(e, "send_provider", None)
        if sp:
            out["provider"] = sp
        stid = getattr(e, "send_provider_thread_id", None)
        if stid:
            out["thread_id"] = stid
        rfc = getattr(e, "send_rfc_message_id", None)
        if rfc:
            out["rfc_message_id"] = rfc
        te = getattr(e, "send_to_email", None)
        if te:
            out["to_email"] = te
        sj = getattr(e, "send_subject", None)
        if sj is not None and sj != "":
            out["subject"] = sj
        fe = getattr(e, "send_from_email", None)
        if fe:
            out["from_email"] = fe
        sac = getattr(e, "send_attachment_count", None)
        if sac is not None:
            out["attachment_count"] = sac
    else:
        eth = getattr(e, "email_thread_id", None)
        if eth is not None:
            out["thread_id"] = eth

    if et == "reply_sent":
        rac = getattr(e, "reply_attachment_count", None)
        if rac is not None:
            out["attachment_count"] = rac
        raaj = getattr(e, "reply_attached_asset_ids_json", None)
        if isinstance(raaj, list) and raaj:
            out["attached_asset_ids"] = raaj

    if et == "replied":
        ife = getattr(e, "inbound_from_email", None)
        if ife:
            out["from_email"] = ife
        ite = getattr(e, "inbound_to_email", None)
        if ite:
            out["to_email"] = ite
        isj = getattr(e, "inbound_subject", None)
        if isj is not None and isj != "":
            out["subject"] = isj

    return out


def apply_split_payload_to_event(event: Any, payload: dict | None, event_type: str) -> None:
    cols, remainder = split_payload_for_storage(
        payload,
        event_type,
        provider_message_id_row=getattr(event, "provider_message_id", None),
    )
    for k, v in cols.items():
        setattr(event, k, v)
    event.payload_json = remainder if remainder else {}


def effective_payload_json(e: Any) -> dict:
    base = build_payload_from_columns(e)
    extra = getattr(e, "payload_json", None)
    if not isinstance(extra, dict):
        extra = {}
    return {**base, **extra}


def should_skip_payload_backfill(e: Any, merged: dict) -> bool:
    """Avoid re-running split on every startup when only remainder extras remain."""
    if getattr(e, "payload_source", None) is not None:
        return True
    if not merged:
        return True
    extras_only = frozenset({"accepted", "attachment_ids"})
    if getattr(e, "send_provider", None) and set(merged.keys()) <= extras_only:
        return True
    return False
