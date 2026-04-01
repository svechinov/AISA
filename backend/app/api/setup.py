"""First-run integration: LLM + CDN keys (optional .env write when explicitly allowed)."""

import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.services.env_bootstrap import (
    ENV_FILE_PATH,
    LLM_KEY_BY_PROVIDER,
    VALID_LLM,
    bootstrap_env_write_allowed,
    build_setup_hints,
    env_write_blocked_reason,
    cdn_configured_from_environ,
    cdn_provider_id_from_environ,
    discover_env_files,
    llm_configured_from_environ,
    llm_providers_ready_from_environ,
    load_env_from_file,
    upsert_env_file,
    upsert_env_files_everywhere,
)
from app.services.cdn_upload_service import r2_upload_ready
from app.services.gmail_oauth import (
    GmailOAuthError,
    google_client_configured,
    google_refresh_token_value,
    gmail_profile_email,
    list_send_as_rows,
    refresh_access_token,
    summarize_send_as_rows,
)

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    llm_configured: bool
    cdn_configured: bool
    allow_env_write: bool
    env_paths_found: list[str] = []
    hints: list[str] = []
    llm_providers_ready: list[str] = Field(
        default_factory=list,
        description="LLM provider ids with keys (priority order), e.g. claude, openai.",
    )
    cdn_provider: str = Field(
        "",
        description="CDN_PROVIDER id when set, e.g. cloudflare (empty if unset).",
    )
    cdn_r2_upload_ready: bool = Field(
        False,
        description="True when Cloudflare R2 env is complete for POST /assets/upload (PDF etc.).",
    )
    gmail_client_configured: bool = Field(
        False,
        description="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET present.",
    )
    gmail_refresh_token_set: bool = Field(
        False,
        description="GOOGLE_REFRESH_TOKEN present after successful Connect Gmail.",
    )
    gmail_send_ready: bool = Field(
        False,
        description="True when Gmail client + refresh token are set (sending uses Gmail API).",
    )
    gmail_send_as_email: str = Field(
        "",
        description="If set in .env (GMAIL_SEND_AS_EMAIL), API uses this From when Gmail allows it.",
    )
    email_allow_mock: bool = Field(
        False,
        description="When false, outbound send fails if Gmail is not configured (no silent mock).",
    )
    gmail_preview_recipient_email: str = Field(
        "",
        description="GMAIL_PREVIEW_RECIPIENT_EMAIL if set (legacy/display only; Drafts → Test uses self-send: To = From).",
    )
    env_write_blocked_reason: str = Field(
        "",
        description="Non-empty when the API will refuse to save GOOGLE_REFRESH_TOKEN / setup keys; empty when writes are allowed.",
    )


@router.get("/gmail-send-as-list")
def setup_gmail_send_as_list() -> dict:
    """Verified «Send mail as» addresses for the connected Gmail account (debug GMAIL_SEND_AS_EMAIL)."""
    if not google_client_configured() or not google_refresh_token_value():
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured in this process (see GET /setup/status).",
        )
    try:
        access = refresh_access_token()
        rows = list_send_as_rows(access)
        load_env_from_file()
        env_as = (os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'")
        return {
            "profileEmail": gmail_profile_email(access),
            "gmailSendAsFromEnv": env_as or None,
            "sendAs": summarize_send_as_rows(rows),
        }
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/gmail-mailbox")
def setup_gmail_mailbox() -> dict:
    """Which Gmail account this API sends as (matches users/me/profile). Use when mail seems to disappear."""
    if not google_client_configured() or not google_refresh_token_value():
        raise HTTPException(
            status_code=400,
            detail="Gmail not configured in this process (see GET /setup/status).",
        )
    try:
        access = refresh_access_token()
        return {"emailAddress": gmail_profile_email(access)}
    except GmailOAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/status", response_model=SetupStatus)
def setup_status(response: Response) -> SetupStatus:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    load_env_from_file()
    write_block = env_write_blocked_reason()
    allow = write_block == ""
    llm_ok = llm_configured_from_environ()
    cdn_ok = cdn_configured_from_environ()
    paths = [str(p.resolve()) for p in discover_env_files()]
    hints = build_setup_hints(llm_ok=llm_ok, cdn_ok=cdn_ok, allow_write=allow)
    gc = google_client_configured()
    gr = bool(google_refresh_token_value())
    if not settings.EMAIL_ALLOW_MOCK and not (gc and gr):
        hints.append(
            "Outbound email: EMAIL_ALLOW_MOCK is false — the API will not fake-deliver mail. "
            "Configure Gmail (gmail_send_ready) or set EMAIL_ALLOW_MOCK=true only for offline dev.",
        )
    if gc and not gr:
        hints.append(
            "Gmail setup: Client ID/secret are visible to the API, but GOOGLE_REFRESH_TOKEN is missing or empty. "
            "Confirm the exact name GOOGLE_REFRESH_TOKEN (see backend/.env.example). "
            "If the token is in ai-biz-os/.env and backend/.env, the later path in “Loaded:” wins for duplicates.",
        )
        if not paths:
            hints.append(
                "Gmail setup: No .env file paths were found on disk inside this API process (typical in Docker). "
                "Variables still come from docker-compose env_file / environment at container start only — "
                "editing backend/.env on the host does not update a running container. Recreate the backend service "
                "after you change that file, or bind-mount backend/.env to /app/.env (see infra/docker-compose.bind-env.yml).",
            )
        else:
            hints.append(
                "Gmail setup: If you just pasted GOOGLE_REFRESH_TOKEN into backend/.env and use Docker Compose env_file, "
                "recreate the backend container so the new variable is injected: "
                "`docker compose -f infra/docker-compose.yml up -d --force-recreate backend`.",
            )
        hints.append(
            "Gmail setup: Alternative without browser OAuth: from ai-biz-os/backend run "
            "`python3 scripts/fetch_google_refresh_token.py` (add both redirect URIs in Google Cloud as documented there).",
        )
    return SetupStatus(
        llm_configured=llm_ok,
        cdn_configured=cdn_ok,
        allow_env_write=allow,
        env_write_blocked_reason=write_block,
        env_paths_found=paths,
        hints=hints,
        llm_providers_ready=llm_providers_ready_from_environ(),
        cdn_provider=cdn_provider_id_from_environ(),
        cdn_r2_upload_ready=r2_upload_ready(),
        gmail_client_configured=gc,
        gmail_refresh_token_set=gr,
        gmail_send_ready=gc and gr,
        gmail_send_as_email=(os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'"),
        email_allow_mock=settings.EMAIL_ALLOW_MOCK,
        gmail_preview_recipient_email=(os.environ.get("GMAIL_PREVIEW_RECIPIENT_EMAIL") or "")
        .strip()
        .strip('"')
        .strip("'"),
    )


class LLMRowIn(BaseModel):
    provider: Literal["claude", "openai", "perplexity", "grok"]
    api_key: str = ""


class SetupBootstrapIn(BaseModel):
    """llm_rows preserves UI order (first = highest priority among providers with keys)."""

    llm_rows: list[LLMRowIn] = Field(..., min_length=4, max_length=4)
    cdn_provider: Literal["cloudflare", "akamai", "cloudfront", "gcp_cdn"]
    cdn_api_key: str

    @field_validator("llm_rows")
    @classmethod
    def llm_rows_unique_providers(cls, rows: list[LLMRowIn]) -> list[LLMRowIn]:
        ids = [r.provider for r in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("Each LLM provider must appear exactly once")
        if set(ids) != VALID_LLM:
            raise ValueError("Must include all four LLM providers once")
        return rows


@router.post("/bootstrap")
def setup_bootstrap(body: SetupBootstrapIn) -> dict:
    if not bootstrap_env_write_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Saving to .env is disabled. Set ALLOW_SETUP_ENV_WRITE=true for local development "
                "(never in production), ensure APP_ENV is not production, or edit backend/.env manually."
            ),
        )

    keys_trimmed = {r.provider: (r.api_key or "").strip() for r in body.llm_rows}
    if not any(keys_trimmed.values()):
        raise HTTPException(status_code=422, detail="Provide at least one LLM API key")

    cdn_key = (body.cdn_api_key or "").strip()
    if not cdn_key:
        raise HTTPException(status_code=422, detail="CDN API key is required")

    priority = [p for p in (r.provider for r in body.llm_rows) if keys_trimmed.get(p)]
    priority_csv = ",".join(priority)

    updates: dict[str, str] = {
        "LLM_PROVIDER_PRIORITY": priority_csv,
        "CDN_PROVIDER": body.cdn_provider,
        "CDN_API_KEY": cdn_key,
    }
    for row in body.llm_rows:
        env_key = LLM_KEY_BY_PROVIDER[row.provider]
        updates[env_key] = keys_trimmed[row.provider]

    if not ENV_FILE_PATH.is_file():
        upsert_env_file(
            {
                "APP_ENV": settings.APP_ENV,
                "DATABASE_URL": settings.DATABASE_URL,
                "REDIS_URL": settings.REDIS_URL,
            },
        )

    upsert_env_file(updates)

    return {
        "ok": True,
        "message": "Configuration saved to backend/.env. Reload the page; restart the API if values are not picked up.",
    }


class GmailCredentialsIn(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    redirect_uri: str = Field(
        "",
        description="Optional; if empty, callback URL is built from the browser origin when you click Connect Gmail.",
    )


@router.post("/gmail-credentials")
def setup_gmail_credentials(body: GmailCredentialsIn) -> dict:
    if not bootstrap_env_write_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                "Saving to .env is disabled. Set ALLOW_SETUP_ENV_WRITE=true for local development "
                "(never in production), or edit backend/.env manually."
            ),
        )
    updates: dict[str, str] = {
        "GOOGLE_CLIENT_ID": body.client_id.strip(),
        "GOOGLE_CLIENT_SECRET": body.client_secret.strip(),
    }
    ruri = (body.redirect_uri or "").strip()
    if ruri:
        updates["GOOGLE_REDIRECT_URI"] = ruri
    if not ENV_FILE_PATH.is_file():
        upsert_env_file(
            {
                "APP_ENV": settings.APP_ENV,
                "DATABASE_URL": settings.DATABASE_URL,
                "REDIS_URL": settings.REDIS_URL,
            },
        )
    upsert_env_files_everywhere(updates)
    return {
        "ok": True,
        "message": "Gmail OAuth client saved to .env file(s) listed in GET /setup/status. Restart the API only if values are not picked up.",
    }
