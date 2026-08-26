"""
Minimal /setup/status — imported from app.main at startup without pulling boto3 or heavy Gmail helpers.

Heavy setup routes (bootstrap, Gmail OAuth helpers) live in app.api.setup and register with the async route bundle.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services.env_bootstrap import (
    build_setup_hints,
    cdn_configured_from_environ,
    cdn_provider_id_from_environ,
    discover_env_files,
    env_write_blocked_reason,
    llm_configured_from_environ,
    llm_providers_ready_from_environ,
    load_env_from_file,
    r2_upload_ready_from_environ,
    safe_str_path,
)

logger = logging.getLogger(__name__)

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
    apollo_configured: bool = Field(
        False,
        description="APOLLO_API_KEY present — collect_companies/find_contacts try Apollo first.",
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
    gmail_mailboxes: list[dict] = Field(
        default_factory=list,
        description=(
            "B-071 stage B: per-mailbox Gmail connections beyond the default global mailbox "
            "(Alexey, reported above via gmail_*). Each item: "
            "{mailbox_email, send_as, connected}."
        ),
    )
    dwd_configured: bool = Field(
        False,
        description="B-071 stage C: True when GOOGLE_SA_KEY_FILE/GOOGLE_SA_KEY_JSON is set and parses.",
    )
    dwd_delegated_domains: list[str] = Field(
        default_factory=list,
        description="B-071 stage C: domains from GOOGLE_DWD_DELEGATED_DOMAINS eligible for impersonation.",
    )
    dwd_sa_client_email: str = Field(
        "",
        description="B-071 stage C: service-account client_email from the SA key (safe to show; never the private key).",
    )


@router.get("/status", response_model=SetupStatus)
def setup_status(response: Response) -> SetupStatus:
    """Read .env + os.environ for LLM/CDN/Gmail/R2 flags (R2 via env only — no boto3 on this path)."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    try:
        load_env_from_file()
        write_block = env_write_blocked_reason()
        allow = write_block == ""
        llm_ok = llm_configured_from_environ()
        cdn_ok = cdn_configured_from_environ()
        paths = [safe_str_path(p) for p in discover_env_files()]
        hints = build_setup_hints(llm_ok=llm_ok, cdn_ok=cdn_ok, allow_write=allow)

        r2_ready = r2_upload_ready_from_environ()
        try:
            from app.services.gmail_oauth import (
                dwd_status,
                google_client_configured,
                google_refresh_token_value,
                list_configured_mailboxes,
            )

            gc = google_client_configured()
            gr = bool(google_refresh_token_value())
            gmail_mailboxes = list_configured_mailboxes()
            dwd = dwd_status()
        except Exception as gmail_exc:
            logger.warning("GET /setup/status: Gmail env helpers failed (non-fatal): %s", gmail_exc)
            gc = False
            gr = False
            gmail_mailboxes = []
            dwd = {"dwd_configured": False, "delegated_domains": [], "sa_client_email": ""}
        try:
            from app.services.apollo_service import apollo_configured

            apollo_configured_flag = apollo_configured()
        except Exception as apollo_exc:
            logger.warning("GET /setup/status: Apollo helper failed (non-fatal): %s", apollo_exc)
            apollo_configured_flag = False
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
            cdn_r2_upload_ready=r2_ready,
            gmail_client_configured=gc,
            gmail_refresh_token_set=gr,
            gmail_send_ready=gc and gr,
            gmail_send_as_email=(os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'"),
            apollo_configured=apollo_configured_flag,
            email_allow_mock=settings.EMAIL_ALLOW_MOCK,
            gmail_preview_recipient_email=(os.environ.get("GMAIL_PREVIEW_RECIPIENT_EMAIL") or "")
            .strip()
            .strip('"')
            .strip("'"),
            gmail_mailboxes=gmail_mailboxes,
            dwd_configured=dwd["dwd_configured"],
            dwd_delegated_domains=dwd["delegated_domains"],
            dwd_sa_client_email=dwd["sa_client_email"],
        )
    except Exception as e:
        logger.exception("GET /setup/status failed")
        raise HTTPException(
            status_code=503,
            detail=f"setup_status_unavailable: {type(e).__name__}: {e!s}"[:2000],
        ) from e
