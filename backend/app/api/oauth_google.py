"""Google OAuth for Gmail (single mailbox): start URL, callback, redirect back to UI."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.services.gmail_oauth import (
    GmailOAuthError,
    build_authorization_url,
    google_client_configured,
    reload_google_env,
    resolve_redirect_uri,
    sign_oauth_state,
    verify_gmail_roundtrip_with_code,
    verify_oauth_state,
)

router = APIRouter(prefix="/oauth/google", tags=["oauth-google"])


def _safe_return_path(path: str) -> str:
    p = (path or "/").strip() or "/"
    if not p.startswith("/"):
        p = "/" + p
    if len(p) > 2048 or "\r" in p or "\n" in p or p.startswith("//"):
        raise HTTPException(status_code=400, detail="Invalid return_path")
    if "://" in p:
        raise HTTPException(status_code=400, detail="return_path must be a path, not a URL")
    return p


def _safe_public_origin(origin: str) -> str:
    o = (origin or "").strip().rstrip("/")
    if not o:
        raise HTTPException(status_code=400, detail="public_origin is required")
    u = urllib.parse.urlparse(o)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise HTTPException(status_code=400, detail="public_origin must be http(s) URL")
    host = (u.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost"):
        return o
    if u.scheme == "https":
        return o
    if (settings.APP_ENV or "").lower() != "production":
        return o
    raise HTTPException(
        status_code=400,
        detail="Use https for public_origin in production (or set GOOGLE_REDIRECT_URI in .env).",
    )


class GmailOAuthStartIn(BaseModel):
    """Browser sends the UI origin (window.location.origin) for callback URL construction."""

    public_origin: str = Field(..., description="e.g. http://localhost:5173 or https://app.example.com")
    return_path: str = Field(default="/", description="Path to open after success, e.g. /")


@router.post("/start")
def gmail_oauth_start(body: GmailOAuthStartIn) -> dict[str, str]:
    reload_google_env()
    if not google_client_configured():
        raise HTTPException(
            status_code=400,
            detail="Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (save via setup or .env).",
        )
    pub = _safe_public_origin(body.public_origin)
    ret_path = _safe_return_path(body.return_path)
    redirect_uri = resolve_redirect_uri(pub)
    state = sign_oauth_state(
        {
            "return_path": ret_path,
            "public_origin": pub,
            "redirect_uri": redirect_uri,
        },
    )
    cid = __import__("os").environ.get("GOOGLE_CLIENT_ID", "").strip()
    url = build_authorization_url(client_id=cid, redirect_uri=redirect_uri, state=state)
    return {"authorization_url": url}


@router.get("/callback")
def gmail_oauth_callback(code: str | None = None, state: str | None = None) -> RedirectResponse:
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    try:
        data: dict[str, Any] = verify_oauth_state(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return_path = _safe_return_path(str(data.get("return_path") or "/"))
    public_origin = str(data.get("public_origin") or "").strip().rstrip("/")
    redirect_uri = str(data.get("redirect_uri") or "").strip()
    if not public_origin or not redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid OAuth state payload")

    try:
        verify_gmail_roundtrip_with_code(code, redirect_uri)
    except GmailOAuthError as e:
        dest = f"{public_origin}{return_path}?gmail_error={urllib.parse.quote(str(e))}"
        return RedirectResponse(url=dest, status_code=302)
    except RuntimeError as e:
        # e.g. persist_google_refresh_token when ALLOW_SETUP_ENV_WRITE is off
        dest = f"{public_origin}{return_path}?gmail_error={urllib.parse.quote(str(e))}"
        return RedirectResponse(url=dest, status_code=302)

    dest = f"{public_origin}{return_path}?gmail_connected=1"
    return RedirectResponse(url=dest, status_code=302)
