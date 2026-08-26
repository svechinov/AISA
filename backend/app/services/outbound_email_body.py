"""Draft/signature → MIME-safe HTML + plain-text fallback for Gmail."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.repositories.asset_repo import get_asset
from app.utils.attached_asset_ids import normalize_attached_asset_ids

logger = logging.getLogger(__name__)

_TAG_START = re.compile(r"<\s*[a-zA-Z!/]")
_LIST_ITEM_RE = re.compile(r"^\s*[-–—•*]\s+")

# Правки Анастасии 17.08 (B-533, второй заход): em dash читается как маркер "текст написан ИИ",
# обращение в приветствии — жирным. Оба правила избирательны по персоне (anastasia_style) —
# см. normalize_draft_body_for_email_html.
_GREETING_RU_WORDS = r"(?:здравствуй\w*|добр\w+\s+(?:день|вечер|утро)|привет\w*)"
_GREETING_NAME_EXCLAIM_RE = re.compile(
    r"^([A-ZА-ЯЁ][a-zа-яёA-Za-z]{1,24}(?:\s[A-ZА-ЯЁ][a-zа-яёA-Za-z]{1,24})?)!",
)
_GREETING_NAME_COMMA_RE = re.compile(
    r"^([A-ZА-ЯЁ][a-zа-яёA-Za-z]{1,24}(?:\s[A-ZА-ЯЁ][a-zа-яёA-Za-z]{1,24})?),\s*" + _GREETING_RU_WORDS,
)
_GREETING_AFTER_SALUTATION_RE = re.compile(
    r"^(?:Hello|Hi|Dear)\s+([A-Z][a-zA-Z'-]{1,24}(?:\s[A-Z][a-zA-Z'-]{1,24})?)\s*,",
)

# Вертикальный ритм письма (правка Анастасии 17.08, B-533): между абзацами — ПУСТАЯ строка, не
# половинный отступ. Полузазор 0.55em читался как слитный текст ("небрежность"), и по той же
# причине подпись выглядела приклеенной к последнему абзацу: прощание отделяется этим же отступом
# предыдущего абзаца, отдельного правила ему не нужно. 1.4em при line-height 1.45 ≈ одна строка.
_BLOCK_GAP = "1.4em"


def looks_like_html_fragment(s: str | None) -> bool:
    t = str(s or "").strip()
    return bool(_TAG_START.search(t))


def _normalize_dashes_for_anastasia(text: str) -> str:
    """Em dash (—) -> en dash (–); plain hyphen (-) untouched. Always en dash, never a comma: the
    choice Anastasia gave (comma, or short dash "if necessary") needs sentence grammar to pick
    correctly, and automation doesn't parse grammar — en dash everywhere is the safe default."""
    return text.replace("—", "–")


def _bold_greeting_addressee(escaped_line: str) -> str:
    """Wraps the addressee's name in <strong> on a confidently-recognized greeting line
    (Анастасия правка 17.08, B-533). A bare "<Capitalized word>," alone is NOT enough — e.g.
    "Коллеги," addresses a group, not a person — so the comma form requires a Russian greeting
    word right after the name; "!" right after the name, or the Hello/Hi/Dear salutation forms,
    are confident enough on their own. No confident match -> line returned unchanged."""
    m = _GREETING_AFTER_SALUTATION_RE.match(escaped_line)
    if not m:
        m = _GREETING_NAME_EXCLAIM_RE.match(escaped_line) or _GREETING_NAME_COMMA_RE.match(escaped_line)
    if not m:
        return escaped_line
    name = m.group(1)
    return escaped_line[: m.start(1)] + f"<strong>{name}</strong>" + escaped_line[m.end(1) :]


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


def _lines_to_paragraph(lines: list[str], *, bold_first_line: bool = False) -> str:
    escaped = [html.escape(line) for line in lines]
    if bold_first_line and escaped:
        escaped[0] = _bold_greeting_addressee(escaped[0])
    inner = "<br>\n".join(escaped)
    return f'<p style="margin:0 0 {_BLOCK_GAP} 0;line-height:1.45;">{inner}</p>'


def _render_list_block(lines: list[str], *, bold_first_line: bool = False) -> str:
    """Draft-marked list (B-533): leading non-bullet lines -> <p>, the contiguous run of bullet
    lines -> <ul>/<li>, trailing non-bullet lines -> <p>. Only explicit markup produces a list —
    no autodetection beyond the "- "/"– "/"— "/"• "/"* " bullet prefix."""
    i = 0
    intro: list[str] = []
    while i < len(lines) and not _LIST_ITEM_RE.match(lines[i]):
        intro.append(lines[i])
        i += 1
    items: list[str] = []
    while i < len(lines) and _LIST_ITEM_RE.match(lines[i]):
        item_text = _LIST_ITEM_RE.sub("", lines[i], count=1)
        items.append(
            f'<li style="margin:0 0 0.25em 0;line-height:1.45;">{html.escape(item_text)}</li>',
        )
        i += 1
    tail = lines[i:]
    out: list[str] = []
    if intro:
        out.append(_lines_to_paragraph(intro, bold_first_line=bold_first_line))
    out.append(
        f'<ul style="margin:0 0 {_BLOCK_GAP} 0;padding-left:1.25em;">' + "".join(items) + "</ul>",
    )
    if tail:
        out.append(_lines_to_paragraph(tail))
    return "".join(out)


def plain_text_to_email_html(text: str, *, style_dashes: bool = False, style_greeting_bold: bool = False) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    if not raw:
        return ""
    if style_dashes:
        raw = _normalize_dashes_for_anastasia(raw)
    blocks = re.split(r"\n{2,}", raw)
    parts: list[str] = []
    first_block_done = False
    for block in blocks:
        b = block.strip()
        if not b:
            continue
        lines = b.split("\n")
        bold_first = style_greeting_bold and not first_block_done
        first_block_done = True
        if any(_LIST_ITEM_RE.match(line) for line in lines):
            parts.append(_render_list_block(lines, bold_first_line=bold_first))
        else:
            parts.append(_lines_to_paragraph(lines, bold_first_line=bold_first))
    inner_html = "".join(parts)
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#111;">'
        f"{inner_html}"
        "</div>"
    )


def normalize_draft_body_for_email_html(body: str | None, *, anastasia_style: bool = False) -> str:
    """Rich-text HTML from the editor, or plain text with \\n / blank lines.

    anastasia_style (B-533, правка 17.08): em dash -> en dash and greeting-name bolding, for
    Anastasia's persona only (see email_sender.py / reply_sender.py call sites). Default False —
    every other persona (alexey, stepan) renders exactly as before.
    """
    s = str(body or "").strip()
    if not s:
        return ""
    if looks_like_html_fragment(s):
        if anastasia_style:
            s = _normalize_dashes_for_anastasia(s)
        s = _inline_newlines_to_br_in_text_nodes(s)
        return (
            '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.45;color:#111;">'
            f"{s}"
            "</div>"
        )
    return plain_text_to_email_html(s, style_dashes=anastasia_style, style_greeting_bold=anastasia_style)


def append_signature_html_after(
    base_html: str,
    signature_html: str | None,
    *,
    language: str | None = None,
) -> str:
    """Append wrapped run signature after an already-normalized HTML body (no second normalize)."""
    sig = str(signature_html or "").strip()
    base = base_html or ""
    if not sig:
        return base
    sig_block = wrap_signature_html_for_email(sig, language=language)
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
    exclude_asset_ids: set[int] | frozenset[int] | None = None,
) -> str:
    """
    After main body, before signature: horizontal rule, bold «Additional assets», list.
    When a signature follows, omit the trailing <hr> (signature block has border-top).
    When nothing follows the list, add a closing rule if trailing_rule_if_no_signature_below.
    exclude_asset_ids: listed only as MIME attachments elsewhere — omit from this link list.
    """
    ids = normalize_attached_asset_ids(raw_asset_ids)
    if exclude_asset_ids:
        ex = exclude_asset_ids
        ids = [i for i in ids if i not in ex]
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


SIGNATURE_CLOSING_PLACEHOLDER = "{{CLOSING}}"

_SIGNATURE_CLOSING_TEXT = {
    "en": "Best regards,",
    "ru": "С уважением,",
}

_CLOSING_TOKEN_RE = re.compile(
    re.escape(SIGNATURE_CLOSING_PLACEHOLDER) + r"(?:<br\s*/?>|\r\n|\r|\n)?",
)

_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")
_LATIN_RE = re.compile(r"[a-zA-Z]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&[#a-zA-Z0-9]+;")


def pick_signature_language(body_text: str | None, run_language: str | None = None) -> str:
    """Anastasia sends RU and EN out of the same run (B-533), so the closing greeting follows the
    drafted body's own language, not the run's configured language. Counts Cyrillic vs. Latin
    letters in the body; ties or no letters at all fall back to run_language.

    B-546: the body is sometimes HTML (B-544's "Оформление" mode saves it that way on purpose) —
    tags and their attributes (font-family:Arial,Helvetica,sans-serif, href, class, ...) are pure
    Latin and can outnumber Cyrillic letters in an otherwise Russian email, so markup and HTML
    entities (&nbsp;, &amp;, &#160;, ...) are stripped to a space before counting.
    """
    text = _HTML_ENTITY_RE.sub(" ", _HTML_TAG_RE.sub(" ", body_text or ""))
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    if cyr == 0 and lat == 0:
        rl = (run_language or "").strip().lower()
        return "ru" if rl in {"russian", "ru"} else "en"
    return "ru" if cyr > lat else "en"


def wrap_signature_html_for_email(signature_inner: str, *, language: str | None = None) -> str:
    """Tighter line-height than default TipTap; top rule instead of double <br>.

    B-533: when ``signature_inner`` contains SIGNATURE_CLOSING_PLACEHOLDER, that token (plus the
    <br>/newline right after it, if any) is cut and a language-appropriate closing paragraph is
    rendered ABOVE the bordered signature block instead. Signatures without the token render
    exactly as before — no behavior change for personas that don't opt in (alexey, stepan).
    """
    if SIGNATURE_CLOSING_PLACEHOLDER in signature_inner:
        inner = _CLOSING_TOKEN_RE.sub("", signature_inner, count=1)
        closing_text = _SIGNATURE_CLOSING_TEXT["ru" if language == "ru" else "en"]
        closing_html = (
            '<p style="margin:0 0 0.55em 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            f'line-height:1.45;color:#111;">{closing_text}</p>'
        )
        return closing_html + (
            '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #ddd;'
            'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.32;color:#333;">'
            f"{inner}"
            "</div>"
        )
    return (
        '<div style="margin-top:14px;padding-top:10px;border-top:1px solid #ddd;'
        'font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.32;color:#333;">'
        f"{signature_inner}"
        "</div>"
    )


def html_to_plain_text_for_mime(html_fragment: str) -> str:
    """Readable plain part for multipart/alternative (not perfect, avoids one long line)."""
    t = html_fragment or ""
    t = re.sub(r"(?i)<\s*li\b[^>]*>", "\n- ", t)
    t = re.sub(r"(?i)</\s*li\s*>", "\n", t)
    t = re.sub(r"(?i)</\s*(?:ul|ol)\s*>", "\n", t)
    t = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", t)
    t = re.sub(r"(?i)</\s*p\s*>", "\n\n", t)
    t = re.sub(r"(?i)</\s*div\s*>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


SIGNATURE_LOGO_CID = "asa-logo"

_LOGO_ASSET_PATH = Path(__file__).resolve().parents[1] / "assets" / "asa-logo.png"
_logo_bytes_cache: bytes | None = None
_logo_bytes_loaded = False


def _load_logo_bytes() -> bytes | None:
    """Lazy, cached read of the signature logo asset (backend/app/assets/asa-logo.png, shipped in
    the Docker image via `COPY app ./app`). Missing file -> None, logged once, so a broken asset
    degrades to the signature's alt text instead of failing the send."""
    global _logo_bytes_cache, _logo_bytes_loaded
    if not _logo_bytes_loaded:
        _logo_bytes_loaded = True
        try:
            _logo_bytes_cache = _LOGO_ASSET_PATH.read_bytes()
        except OSError:
            logger.warning("Signature logo asset not found at %s", _LOGO_ASSET_PATH)
            _logo_bytes_cache = None
    return _logo_bytes_cache


def inline_images_for_email_html(body_html: str) -> list[dict]:
    """cid: images referenced in body_html, ready for the MIME transport's multipart/related part
    (B-533). Only the signature logo exists today (SIGNATURE_LOGO_CID)."""
    if f"cid:{SIGNATURE_LOGO_CID}" not in (body_html or ""):
        return []
    data = _load_logo_bytes()
    if not data:
        return []
    return [
        {
            "cid": SIGNATURE_LOGO_CID,
            "filename": "asa-logo.png",
            "mime_type": "image/png",
            "content": data,
        },
    ]
