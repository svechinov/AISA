"""Resolve which packet assets become real MIME attachments vs link-only Materials: lines."""

from __future__ import annotations

import mimetypes
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_packet import AssetPacket
from app.repositories.asset_repo import get_asset
from app.services.asset_packet_service import get_ordered_asset_refs_for_packet
from app.services.cdn_upload_service import r2_get_object_bytes, r2_upload_ready

# Conservative default; real provider can override via env later.
MAX_ATTACHMENT_BYTES = int(os.environ.get("MAX_EMAIL_ATTACHMENT_BYTES", str(25 * 1024 * 1024)))
MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES = int(
    os.environ.get("MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES", str(50 * 1024 * 1024)),
)
ASSET_STORAGE_ROOT = os.environ.get("ASSET_STORAGE_ROOT", "").strip()
URL_FETCH_TIMEOUT_SEC = float(os.environ.get("ATTACHMENT_URL_FETCH_TIMEOUT", "30"))

# Browser-like headers: some CDNs/R2 public buckets reject minimal urllib clients.
ATTACHMENT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _is_r2_s3_api_host(url: str) -> bool:
    """R2 S3 endpoint is not for anonymous HTTP GET; use GetObject with credentials."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith(".r2.cloudflarestorage.com")


def _norm_key_part(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def dedupe_sendable_attachments(sendable: list[dict], skipped: list[dict]) -> list[dict]:
    """Same physical/source identity only once per email (per asset file_path / download_url / storage_key)."""
    seen: set[tuple[str | None, str | None, str | None]] = set()
    unique: list[dict] = []
    for a in sendable:
        key = (
            _norm_key_part(a.get("file_path")),
            _norm_key_part(a.get("download_url")),
            _norm_key_part(a.get("storage_key")),
        )
        if key in seen:
            _append_skip(skipped, a.get("asset_id"), "duplicate attachment source in packet")
            continue
        seen.add(key)
        unique.append(a)
    return unique


def _effective_size_for_total_cap(meta: dict) -> int:
    """Bytes counted toward total payload budget; unknown URL size treated pessimistically."""
    sz = meta.get("file_size_bytes")
    if sz is not None:
        return int(sz)
    if meta.get("download_url"):
        return MAX_ATTACHMENT_BYTES
    return 0


def apply_total_attachment_budget(
    db: Session,
    sendable: list[dict],
    link_only: list[dict],
    skipped: list[dict],
) -> list[dict]:
    """
    Enforce MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES on cumulative payload. Per attachment, uses
    file_size_bytes when set; if missing and source is download_url, assumes MAX_ATTACHMENT_BYTES.
    When adding the next file would exceed the budget, that asset becomes link-only.
    """
    running = 0
    kept: list[dict] = []
    for meta in sendable:
        eff = _effective_size_for_total_cap(meta)
        if running + eff > MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES:
            asset = get_asset(db, meta["asset_id"]) if meta.get("asset_id") else None
            link_only.append(_merge_ref_for_link(asset, {"asset_id": meta.get("asset_id")}))
            _append_skip(
                skipped,
                meta.get("asset_id"),
                "exceeds total attachment budget for this email",
            )
            continue
        running += eff
        kept.append(meta)
    return kept


def finalize_sendable_attachments(
    db: Session,
    sendable: list[dict],
    link_only: list[dict],
    skipped: list[dict],
) -> list[dict]:
    sendable = dedupe_sendable_attachments(sendable, skipped)
    return apply_total_attachment_budget(db, sendable, link_only, skipped)


def _guess_mime(filename: str, asset: Asset | None) -> str:
    if asset and asset.mime_type:
        return asset.mime_type
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def _resolve_display_filename(asset: Asset | None, ref: dict, local_path: str | None) -> str | None:
    if asset and asset.filename and asset.filename.strip():
        return asset.filename.strip()
    if local_path:
        base = os.path.basename(local_path)
        if base:
            return base
    dn = ref.get("filename") or ref.get("name")
    if dn and str(dn).strip():
        return str(dn).strip()
    if asset and asset.name:
        return asset.name
    return None


def _local_path_for_asset(asset: Asset) -> str | None:
    if asset.file_path and str(asset.file_path).strip():
        p = os.path.abspath(os.path.expanduser(asset.file_path.strip()))
        if os.path.isfile(p):
            return p
    if asset.storage_key and str(asset.storage_key).strip():
        key = asset.storage_key.strip()
        if ASSET_STORAGE_ROOT:
            p = os.path.abspath(os.path.join(ASSET_STORAGE_ROOT, key))
        else:
            p = os.path.abspath(os.path.expanduser(key))
        if os.path.isfile(p):
            return p
    return None


def _file_size(local_path: str) -> int:
    return os.path.getsize(local_path)


def _verify_readable(local_path: str) -> None:
    with open(local_path, "rb") as f:
        if not f.read(1):
            return
    # non-empty read at least one byte; empty file still attachable
    with open(local_path, "rb") as f:
        f.read(1)


def _fetch_url_content_length(url: str) -> int | None:
    """
    Best-effort Content-Length (HEAD, then streaming GET headers only).
    Returns None if reachable but length unknown. Raises OSError if unreachable.
    """
    timeout = httpx.Timeout(URL_FETCH_TIMEOUT_SEC)
    last_err: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        try:
            h = client.head(url, headers=ATTACHMENT_HTTP_HEADERS)
            if not h.is_error:
                cl = h.headers.get("content-length")
                if cl and str(cl).isdigit():
                    return int(cl)
        except httpx.HTTPError as e:
            last_err = e
        try:
            with client.stream("GET", url, headers=ATTACHMENT_HTTP_HEADERS) as r:
                r.raise_for_status()
                cl = r.headers.get("content-length")
                if cl and str(cl).isdigit():
                    return int(cl)
        except httpx.HTTPError as e:
            raise OSError(str(e)) from (last_err or e)
    return None


def _merge_ref_for_link(asset: Asset | None, ref: dict) -> dict:
    out: dict[str, Any] = dict(ref)
    if asset:
        out.setdefault("name", asset.name)
        out.setdefault("asset_type", asset.asset_type)
        out.setdefault("title", asset.name)
        out.setdefault(
            "url",
            ref.get("url") or asset.url or (asset.download_url or None),
        )
        out.setdefault("file_url", ref.get("file_url"))
        out.setdefault("file_path", ref.get("file_path") or asset.file_path)
    return out


def _append_skip(skipped: list[dict], asset_id: int | None, reason: str) -> None:
    skipped.append({"asset_id": asset_id, "reason": reason})


def resolve_sendable_attachments_for_asset_ids(
    db: Session,
    asset_ids: list[int],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Reuse packet resolution for a plain ordered list of library asset ids (draft attachments)."""
    refs: list[dict] = []
    for raw in asset_ids:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            continue
        refs.append({"asset_id": aid})
    fake = SimpleNamespace(status="draft", packet_json={"assets": refs})
    return resolve_sendable_attachments(db, fake)  # type: ignore[arg-type]


def resolve_sendable_attachments(
    db: Session,
    packet: AssetPacket,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Returns (sendable_metas, link_only_asset_dicts, skipped).

    sendable_metas: rows with keys asset_id, filename, mime_type, local_path|download_url, source_path, source_url
    link_only_asset_dicts: passed to render_assets_block_for_email (no duplicate of sendable assets)
    """
    if packet.status == "archived":
        return [], [], []

    sendable: list[dict] = []
    link_only: list[dict] = []
    skipped: list[dict] = []

    for ref in get_ordered_asset_refs_for_packet(db, packet):
        if not isinstance(ref, dict):
            continue
        aid = ref.get("asset_id")
        asset: Asset | None = get_asset(db, aid) if aid else None

        if not aid or not asset:
            link_only.append(_merge_ref_for_link(asset, ref))
            if aid:
                _append_skip(skipped, int(aid), "asset not found or missing id")
            continue

        if asset.status != "active":
            link_only.append(_merge_ref_for_link(asset, ref))
            _append_skip(skipped, asset.id, "asset not active")
            continue

        local_path = _local_path_for_asset(asset)
        download_url = (asset.download_url or "").strip() or None

        if local_path:
            fname = _resolve_display_filename(asset, ref, local_path)
            if not fname:
                link_only.append(_merge_ref_for_link(asset, ref))
                _append_skip(skipped, asset.id, "could not resolve filename")
                continue
            try:
                sz = asset.file_size_bytes if asset.file_size_bytes is not None else _file_size(local_path)
                if sz > MAX_ATTACHMENT_BYTES:
                    link_only.append(_merge_ref_for_link(asset, ref))
                    _append_skip(skipped, asset.id, "file exceeds max attachment size")
                    continue
                _verify_readable(local_path)
            except OSError as e:
                link_only.append(_merge_ref_for_link(asset, ref))
                _append_skip(skipped, asset.id, f"not readable: {e}")
                continue

            mime = _guess_mime(fname, asset)
            sendable.append(
                {
                    "asset_id": asset.id,
                    "filename": fname,
                    "mime_type": mime,
                    "local_path": local_path,
                    "download_url": None,
                    "source_path": local_path,
                    "source_url": None,
                    "file_path": _norm_key_part(asset.file_path),
                    "storage_key": _norm_key_part(asset.storage_key),
                    "file_size_bytes": int(sz),
                },
            )
            continue

        if download_url:
            fname = _resolve_display_filename(asset, ref, None)
            if not fname:
                fname = os.path.basename(download_url.split("?")[0]) or f"asset-{asset.id}"

            sk = _norm_key_part(asset.storage_key)
            skip_http_probe = bool(
                sk and r2_upload_ready() and _is_r2_s3_api_host(download_url),
            )

            cl: int | None = None
            if not skip_http_probe:
                try:
                    cl = _fetch_url_content_length(download_url)
                except OSError as e:
                    if asset.file_size_bytes is not None:
                        cl = int(asset.file_size_bytes)
                    elif sk and r2_upload_ready():
                        cl = None
                    else:
                        link_only.append(_merge_ref_for_link(asset, ref))
                        _append_skip(skipped, asset.id, f"download_url not reachable: {e}")
                        continue
            else:
                cl = int(asset.file_size_bytes) if asset.file_size_bytes is not None else None

            eff_size = cl
            if eff_size is None and asset.file_size_bytes is not None:
                eff_size = int(asset.file_size_bytes)
            if eff_size is not None and eff_size > MAX_ATTACHMENT_BYTES:
                link_only.append(_merge_ref_for_link(asset, ref))
                _append_skip(skipped, asset.id, "download_url content exceeds max size")
                continue

            mime = _guess_mime(fname, asset)
            sendable.append(
                {
                    "asset_id": asset.id,
                    "filename": fname,
                    "mime_type": mime,
                    "local_path": None,
                    "download_url": download_url,
                    "source_path": None,
                    "source_url": download_url,
                    "file_path": None,
                    "storage_key": sk,
                    "file_size_bytes": eff_size,
                },
            )
            continue

        # Only page URL or no physical source — link in body only
        link_only.append(_merge_ref_for_link(asset, ref))

    return sendable, link_only, skipped


def materialize_attachment(meta: dict) -> tuple[bytes, str, str]:
    """Load file bytes for provider. Raises if source unavailable."""
    filename = meta["filename"]
    mime = meta["mime_type"]
    if meta.get("local_path"):
        path = meta["local_path"]
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise ValueError("attachment exceeds max size")
        return data, filename, mime

    url = ((meta.get("download_url") or "") or "").strip() or None
    sk = _norm_key_part(meta.get("storage_key"))

    if sk and r2_upload_ready() and url and _is_r2_s3_api_host(url):
        data = r2_get_object_bytes(sk, max_bytes=MAX_ATTACHMENT_BYTES)
        return data, filename, mime

    if sk and r2_upload_ready() and not url:
        data = r2_get_object_bytes(sk, max_bytes=MAX_ATTACHMENT_BYTES)
        return data, filename, mime

    if not url:
        raise ValueError("no attachment source")

    timeout = httpx.Timeout(URL_FETCH_TIMEOUT_SEC)
    chunks: list[bytes] = []
    total = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=ATTACHMENT_HTTP_HEADERS) as r:
                r.raise_for_status()
                for block in r.iter_bytes(65536):
                    total += len(block)
                    if total > MAX_ATTACHMENT_BYTES:
                        raise ValueError("download exceeds max attachment size")
                    chunks.append(block)
    except httpx.HTTPStatusError as e:
        if (
            sk
            and r2_upload_ready()
            and e.response is not None
            and e.response.status_code in (400, 401, 403, 404)
        ):
            data = r2_get_object_bytes(sk, max_bytes=MAX_ATTACHMENT_BYTES)
            return data, filename, mime
        raise OSError(f"attachment download failed: {e}") from e
    except httpx.HTTPError as e:
        if sk and r2_upload_ready():
            try:
                data = r2_get_object_bytes(sk, max_bytes=MAX_ATTACHMENT_BYTES)
                return data, filename, mime
            except OSError:
                pass
        raise OSError(f"attachment download failed: {e}") from e
    return b"".join(chunks), filename, mime
