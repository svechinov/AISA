"""Upload user files to project CDN (Cloudflare R2 or Cloudflare Images for images only)."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import uuid
from typing import Any

import boto3
import httpx
from botocore.config import Config as BotoConfig

from app.services.env_bootstrap import load_env_from_file


def _e(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _prov() -> str:
    return _e("CDN_PROVIDER").lower()


def _r2_secret() -> str:
    return _e("CDN_R2_SECRET_ACCESS_KEY") or _e("CDN_API_KEY")


def r2_upload_ready() -> bool:
    """
    Read live env from disk via load_env_from_file — not the process Settings snapshot,
    so edits to backend/.env apply without restarting uvicorn.
    """
    load_env_from_file()
    return bool(
        _prov() == "cloudflare"
        and _e("CDN_ACCOUNT_ID")
        and _e("CDN_R2_BUCKET")
        and _e("CDN_R2_ACCESS_KEY_ID")
        and _r2_secret()
        and _e("CDN_R2_PUBLIC_BASE_URL")
    )


def cf_images_upload_ready() -> bool:
    load_env_from_file()
    return bool(
        _prov() == "cloudflare"
        and _e("CDN_ACCOUNT_ID")
        and _e("CDN_API_KEY")
    )


def upload_max_bytes() -> int:
    load_env_from_file()
    try:
        mb = int(os.environ.get("CDN_UPLOAD_MAX_BYTES_MB", "50"))
    except ValueError:
        mb = 50
    mb = max(1, min(500, mb))
    return mb * 1024 * 1024


def _safe_suffix(filename: str) -> str:
    base = re.sub(r"^.*[/\\]", "", filename or "file")
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", base).strip("._") or "file"
    return base[:180]


def upload_bytes_to_project_cdn(
    data: bytes,
    *,
    original_filename: str,
    content_type: str | None = None,
) -> dict[str, Any]:
    """
    Returns dict: url, storage_key, filename, mime_type, file_size_bytes, metadata_json (provider hint).
    Raises ValueError with user-facing message if CDN is not configured.
    """
    load_env_from_file()
    max_b = upload_max_bytes()
    if len(data) > max_b:
        raise ValueError(f"File too large (max {max_b // (1024 * 1024)} MB).")

    ct = (content_type or "").strip() or mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
    suffix = _safe_suffix(original_filename)
    key = f"assets/{uuid.uuid4().hex}_{suffix}"

    if r2_upload_ready():
        return _upload_r2(data, key=key, content_type=ct, original_filename=original_filename)

    if cf_images_upload_ready() and ct.startswith("image/"):
        return _upload_cf_images(data, original_filename=original_filename, content_type=ct)

    if _prov() == "cloudflare" and not r2_upload_ready():
        raise ValueError(
            "File upload requires Cloudflare R2: set CDN_ACCOUNT_ID, CDN_R2_BUCKET, "
            "CDN_R2_ACCESS_KEY_ID, CDN_R2_SECRET_ACCESS_KEY (or use CDN_API_KEY as the secret), "
            "and CDN_R2_PUBLIC_BASE_URL. For images only, R2 can be omitted if Cloudflare Images is enabled."
        )

    raise ValueError(
        "File upload is only implemented for CDN_PROVIDER=cloudflare with R2 (or Cloudflare Images for images)."
    )


def _upload_r2(
    data: bytes,
    *,
    key: str,
    content_type: str,
    original_filename: str,
) -> dict[str, Any]:
    load_env_from_file()
    account = _e("CDN_ACCOUNT_ID")
    bucket = _e("CDN_R2_BUCKET")
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_e("CDN_R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_r2_secret(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    base = _e("CDN_R2_PUBLIC_BASE_URL").rstrip("/")
    public_url = f"{base}/{key}"
    return {
        "url": public_url,
        "storage_key": key,
        "filename": original_filename,
        "mime_type": content_type,
        "file_size_bytes": len(data),
        "metadata_json": {"cdn": "cloudflare_r2", "bucket": bucket},
    }


def r2_get_object_bytes(storage_key: str, *, max_bytes: int) -> bytes:
    """
    Fetch object bytes via S3 API (same credentials as upload).
    Use when download_url points at the API host *.r2.cloudflarestorage.com — unauthenticated GET there returns 400.
    """
    load_env_from_file()
    if not r2_upload_ready():
        raise OSError("R2 is not configured (cannot fetch via S3 API)")
    key = (storage_key or "").strip()
    if not key:
        raise ValueError("storage_key is empty")
    account = _e("CDN_ACCOUNT_ID")
    bucket = _e("CDN_R2_BUCKET")
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_e("CDN_R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_r2_secret(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )
    resp = client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"]
    chunks: list[bytes] = []
    total = 0
    while True:
        block = body.read(65536)
        if not block:
            break
        total += len(block)
        if total > max_bytes:
            raise ValueError("attachment exceeds max size")
        chunks.append(block)
    return b"".join(chunks)


def _upload_cf_images(data: bytes, *, original_filename: str, content_type: str) -> dict[str, Any]:
    load_env_from_file()
    account = _e("CDN_ACCOUNT_ID")
    token = _e("CDN_API_KEY")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/images/v1"
    files = {"file": (original_filename or "upload", data, content_type)}
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, files=files)
    try:
        payload = resp.json()
    except json.JSONDecodeError as e:
        raise ValueError(f"CDN response was not JSON ({resp.status_code}).") from e
    if not payload.get("success"):
        errs = payload.get("errors") or payload
        raise ValueError(f"Cloudflare Images upload failed: {errs}")
    result = payload.get("result") or {}
    variants = result.get("variants") if isinstance(result.get("variants"), list) else []
    public = variants[0] if variants else None
    if not public:
        raise ValueError("Cloudflare Images did not return a public URL (variants missing).")
    image_id = result.get("id")
    return {
        "url": public,
        "storage_key": str(image_id) if image_id else None,
        "filename": original_filename,
        "mime_type": content_type,
        "file_size_bytes": len(data),
        "metadata_json": {"cdn": "cloudflare_images", "image_id": image_id},
    }
