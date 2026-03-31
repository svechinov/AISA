"""Draft/signature → MIME-safe HTML + plain-text fallback for Gmail."""

from __future__ import annotations

import html
import re

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.repositories.asset_repo import get_asset
from app.utils.attached_asset_ids import normalize_attached_asset_ids

_TAG_START = re.compile(r"<\s*[a-zA-Z!/]")


def looks_like_html_fragment(s: str | None) -> bool:
    t = str(s or "").strip()
    return bool(_TAG_START.search(t))


def _inline_newlines_to_br_in_text_nodes(html_fragment: str) -> str:
    """Turn literal newlines inside text nodes into <br> (HTML ignores bare \\n)."""
    if "\n" not in html_fragment and "\r" not in html_fragment:
        return html_fragment
    out: list[str] = []
    i, n = 0, len(html_fragment)
    while i < n:
        if html_fragment[i] == "<":
            j = html_fragment.find(">", i)
            if j < 0:
                out.append(html_fragment[i:])
                break
            out.append(html_fragment[i : j + 1])
            i = j + 1
            continue
        j = i
        while j < n and html_fragment[j] != "<":
            j += 1
        chunk = html_fragment[i:j].replace("\r\n", "\n").replace("\r", "\n")
        chunk = chunk.replace("\n", "<br>\n")
        out.append(chunk)
        i = j
    return "".join(out)


def plain_text_to_email_html(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    if not raw:
        return ""
    blocks = re.split(r"\n{2,}", raw)
    parts: list[str] = []
    for block in blocks:
        b = block.strip()
        if not b:
            continue
        lines = b.split("\n")
        inner = "<br>\n".join(html.escape(line) for line in lines)
        parts.append(f'<p style="margin:0 0 0.55em 0;line-height:1.45;">{inner}</p>')
    inner_html = "".join(parts)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#111;">'
        f"{inner_html}"
        "</div>"
    )


def normalize_draft_body_for_email_html(body: str | None) -> str:
    """Rich-text HTML from the editor, or plain text with \\n / blank lines."""
    s = str(body or "").strip()
    if not s:
        return ""
    if looks_like_html_fragment(s):
        s = _inline_newlines_to_br_in_text_nodes(s)
        return (
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#111;">'
            f"{s}"
            "</div>"
        )
    return plain_text_to_email_html(s)


def append_signature_html_after(base_html: str, signature_html: str | None) -> str:
    """Append wrapped run signature after an already-normalized HTML body (no second normalize)."""
    sig = str(signature_html or "").strip()
    base = base_html or ""
    if not sig:
        return base
    sig_block = wrap_signature_html_for_email(sig)
    if not base.strip():
        return sig_block
    return f"{base}\n{sig_block}"


def _asset_href_for_email(asset: Asset | None) -> str | None:
    if not asset:
        return None
    for attr in ("url", "download_url"):
        v = getattr(asset, attr, None)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def append_additional_assets_section_to_email_html(
    body_html: str,
    db: Session,
    raw_asset_ids: object,
    *,
    trailing_rule_if_no_signature_below: bool = True,
) -> str:
    """
    After main body, before signature: horizontal rule, bold «Additional assets», list.
    When a signature follows, omit the trailing <hr> (signature block has border-top).
    When nothing follows the list, add a closing rule if trailing_rule_if_no_signature_below.
    """
    ids = normalize_attached_asset_ids(raw_asset_ids)
    if not ids:
        return body_html or ""
    items: list[str] = []
    for aid in ids:
        asset = get_asset(db, aid)
        label = (asset.name or "").strip() if asset else ""
        if not label:
            label = f"Asset #{aid}"
        label_esc = html.escape(label)
        href = _asset_href_for_email(asset)
        if href:
            href_esc = html.escape(href, quote=True)
            items.append(
                "<li>"
                f'<a href="{href_esc}" style="color:#1a0dab;text-decoration:underline;">{label_esc}</a>'
                "</li>",
            )
        else:
            items.append(f"<li>{label_esc}</li>")
    tail = ""
    if trailing_rule_if_no_signature_below:
        tail = '<hr style="border:none;border-top:1px solid #ddd;margin:12px 0 0 0;">'
    block = (
        '<hr style="border:none;border-top:1px solid #ddd;margin:16px 0 12px 0;">'
        '<p style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:1.45;color:#111;"><strong>Additional assets</strong></p>'
        '<ul style="margin:0 0 12px 0;padding-left:1.25em;font-family:Arial,Helvetica,sans-serif;'
        'font-size:14px;line-height:1.45;color:#111;">'
        + "".join(items)
        + "</ul>"
        + tail
    )
    return (body_html or "") + block


def wrap_signature_html_for_email(signature_inner: str) -> str:
    """Tighter line-height than default TipTap; top rule instead of double <br>."""
    return (
        '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #ddd;'
        'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.32;color:#333;">'
        f"{signature_inner}"
        "</div>"
    )


def html_to_plain_text_for_mime(html_fragment: str) -> str:
    """Readable plain part for multipart/alternative (not perfect, avoids one long line)."""
    t = html_fragment or ""
    t = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", t)
    t = re.sub(r"(?i)</\s*p\s*>", "\n\n", t)
    t = re.sub(r"(?i)</\s*div\s*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
