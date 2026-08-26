"""Google OAuth (offline) + Gmail REST helpers: token exchange, refresh, send, verify roundtrip.

B-071 stage B (multi-mailbox): the single Google OAuth client (GOOGLE_CLIENT_ID/SECRET) is shared
across accounts, but each non-default mailbox (e.g. Stepan, Alexey's mailbox #2) gets its own
refresh token + send-as address, stored in the server .env as one JSON key per mailbox:

    GMAIL_ACCOUNT__<SLUG>={"send_as": "stepan@alexstaff.agency", "refresh_token": "1//..."}

<SLUG> is the mailbox email, uppercased, with every non-alphanumeric character (@/./-/...)
collapsed to "_" — e.g. stepan@alexstaff.agency -> GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY.

HARD INVARIANT: every creds-resolving function below takes an optional ``mailbox_email``
parameter, defaulting to None. When it's None, or when it's set but no GMAIL_ACCOUNT__<SLUG> key
exists for it, resolution falls back byte-for-byte to today's globals (GOOGLE_REFRESH_TOKEN /
GMAIL_SEND_AS_EMAIL) — Alexey's mailbox behavior does not change when no per-mailbox keys are
configured.

B-071 stage C (domain-wide delegation): a single Google service account can impersonate any
mailbox on a delegated Workspace domain (e.g. alexstaff.agency) without per-user OAuth consent.
Configured via:

    GOOGLE_SA_KEY_FILE=/app/data/sa-key.json      (path to the SA JSON key; takes priority)
    GOOGLE_SA_KEY_JSON={"client_email": ..., ...} (inline JSON alternative)
    GOOGLE_DWD_DELEGATED_DOMAINS=alexstaff.agency  (comma-separated domains eligible for DWD)

DWD is a *last-resort* resolution step (see _uses_dwd/refresh_access_token): it only fires for a
mailbox that is (a) not the global mailbox (Alexey) and (b) has no GMAIL_ACCOUNT__<SLUG> entry of
its own. Without GOOGLE_SA_KEY_FILE/GOOGLE_SA_KEY_JSON set, _dwd_configured() is False and every
function in this module behaves exactly as in stage B.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes as crypto_hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as crypto_padding

from app.config import settings
from app.services.outbound_email_body import html_to_plain_text_for_mime
from app.services.env_bootstrap import (
    bootstrap_env_write_allowed,
    env_write_blocked_reason,
    load_env_from_file,
    peek_env_key_from_files,
    upsert_env_file,
    upsert_env_files_everywhere,
)

# send — outbound (+ replies via messages.send). modify — read threads/messages, labels, trash (not delete-bypass).
# Profile email comes from Gmail users.me.profile (no separate userinfo.email scope — easier in OAuth Playground).
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

VERIFY_SUBJECT = "Business outreach dashboard check"
VERIFY_BODY_TEXT = "AI Biz OS — Gmail connection check."

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


class GmailOAuthError(Exception):
    """Refresh / token exchange failed (invalid_grant etc.)."""


def _state_secret() -> str:
    s = (settings.OAUTH_STATE_SECRET or "").strip()
    if s:
        return s
    return hashlib.sha256(settings.DATABASE_URL.encode()).hexdigest()[:48]


def sign_oauth_state(payload: dict) -> str:
    payload = {**payload, "iat": int(time.time())}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(_state_secret().encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_oauth_state(token: str, *, max_age_sec: int = 900) -> dict:
    try:
        b64, sig = token.split(".", 1)
    except ValueError as e:
        raise ValueError("invalid state") from e
    exp = hmac.new(_state_secret().encode(), b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(exp, sig):
        raise ValueError("invalid state signature")
    pad = "=" * (-len(b64) % 4)
    data = json.loads(base64.urlsafe_b64decode(b64 + pad))
    if int(time.time()) - int(data.get("iat", 0)) > max_age_sec:
        raise ValueError("state expired")
    return data


def reload_google_env() -> None:
    load_env_from_file()


def google_client_configured() -> bool:
    reload_google_env()
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return bool(cid and sec)


def _slug_for_mailbox(mailbox_email: str) -> str:
    """stepan@alexstaff.agency -> STEPAN_ALEXSTAFF_AGENCY (see module docstring for the format)."""
    return re.sub(r"[^A-Za-z0-9]", "_", mailbox_email.strip()).upper()


def _global_refresh_token_value() -> str:
    """Today's single-mailbox refresh token (GOOGLE_REFRESH_TOKEN) — the fallback target for any
    mailbox without its own GMAIL_ACCOUNT__<SLUG> entry, and for mailbox_email=None."""
    reload_google_env()
    v = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
    if v:
        return v
    return peek_env_key_from_files("GOOGLE_REFRESH_TOKEN")


def _mailbox_creds(mailbox_email: str | None) -> dict[str, Any]:
    """Resolve {"refresh_token", "send_as", "found"} for a mailbox.

    ``found`` is True only when a GMAIL_ACCOUNT__<SLUG> entry exists AND carries a non-empty
    refresh_token. Otherwise (mailbox_email empty, no entry, or entry malformed/incomplete) this
    falls back to the global GOOGLE_REFRESH_TOKEN / GMAIL_SEND_AS_EMAIL — today's behavior.
    """
    em = (mailbox_email or "").strip()
    if em:
        reload_google_env()
        key = f"GMAIL_ACCOUNT__{_slug_for_mailbox(em)}"
        raw = os.environ.get(key, "").strip() or peek_env_key_from_files(key)
        if raw:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = None
            if isinstance(data, dict):
                refresh = str(data.get("refresh_token") or "").strip()
                if refresh:
                    send_as = str(data.get("send_as") or "").strip() or em
                    return {"refresh_token": refresh, "send_as": send_as, "found": True}
    reload_google_env()
    return {
        "refresh_token": _global_refresh_token_value(),
        "send_as": (os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'"),
        "found": False,
    }


def google_refresh_token_value(mailbox_email: str | None = None) -> str:
    return str(_mailbox_creds(mailbox_email)["refresh_token"])


# ---------------------------------------------------------------------------------------------
# B-071 stage C — domain-wide delegation (service-account JWT-bearer impersonation)
# ---------------------------------------------------------------------------------------------

_SA_KEY_CACHE: dict[str, Any] | None = None
_SA_KEY_CACHE_SOURCE: str | None = None
_IMPERSONATED_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _load_sa_key() -> dict[str, Any] | None:
    """Parse the service-account JSON key: GOOGLE_SA_KEY_FILE (path) takes priority over
    GOOGLE_SA_KEY_JSON (inline JSON). Returns {"client_email", "private_key", "token_uri"} or
    None when neither var is set, the file can't be read, or the JSON is missing required fields.
    Cached until the underlying env value (path or inline JSON string) changes."""
    global _SA_KEY_CACHE, _SA_KEY_CACHE_SOURCE
    reload_google_env()
    key_file = os.environ.get("GOOGLE_SA_KEY_FILE", "").strip()
    key_json = os.environ.get("GOOGLE_SA_KEY_JSON", "").strip()
    source = f"file:{key_file}" if key_file else (f"json:{key_json}" if key_json else "")
    if not source:
        _SA_KEY_CACHE = None
        _SA_KEY_CACHE_SOURCE = None
        return None
    if source == _SA_KEY_CACHE_SOURCE and _SA_KEY_CACHE is not None:
        return _SA_KEY_CACHE
    if key_file:
        try:
            raw = Path(key_file).read_text(encoding="utf-8")
        except OSError:
            return None
    else:
        raw = key_json
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    client_email = str(data.get("client_email") or "").strip()
    private_key = str(data.get("private_key") or "").strip()
    if not client_email or not private_key:
        return None
    token_uri = str(data.get("token_uri") or "").strip() or GOOGLE_TOKEN
    parsed = {"client_email": client_email, "private_key": private_key, "token_uri": token_uri}
    _SA_KEY_CACHE = parsed
    _SA_KEY_CACHE_SOURCE = source
    return parsed


def _dwd_configured() -> bool:
    return _load_sa_key() is not None


def _dwd_delegated_domains() -> set[str]:
    reload_google_env()
    raw = os.environ.get("GOOGLE_DWD_DELEGATED_DOMAINS", "").strip()
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _dwd_eligible(mailbox_email: str) -> bool:
    """True when mailbox_email's domain is in GOOGLE_DWD_DELEGATED_DOMAINS and the SA key is
    configured. Domain matching alone is not a safe gate — callers (see _uses_dwd) must first rule
    out the global mailbox (Alexey), since he can live on the same delegated domain."""
    if not _dwd_configured():
        return False
    domain = mailbox_email.rsplit("@", 1)[-1].strip().lower() if "@" in mailbox_email else ""
    if not domain:
        return False
    return domain in _dwd_delegated_domains()


def _uses_dwd(mailbox_email: str | None) -> bool:
    """True when refresh_access_token(mailbox_email) resolves via DWD impersonation rather than a
    stored user-OAuth refresh token. Re-derived from mailbox_email alone (not threaded as extra
    state) so every caller — refresh_access_token, resolve_outbound_from_mime — reasons the same
    way, same style as _mailbox_creds. Order (HARD INVARIANT, protects Alexey's mailbox):
      1. mailbox_email empty or equal to the global GMAIL_SEND_AS_EMAIL -> False (global mailbox).
      2. mailbox_email has its own GMAIL_ACCOUNT__<SLUG> entry (stage B) -> False.
      3. otherwise -> True iff the mailbox's domain is DWD-eligible.
    """
    em = (mailbox_email or "").strip()
    if not em:
        return False
    reload_google_env()
    global_send_as = (os.environ.get("GMAIL_SEND_AS_EMAIL") or "").strip().strip('"').strip("'")
    if em.lower() == global_send_as.lower():
        return False
    if _mailbox_creds(em)["found"]:
        return False
    return _dwd_eligible(em)


def _impersonated_access_token(subject_email: str) -> str:
    """Mint a Gmail access token impersonating subject_email via the service account's JWT-bearer
    grant (RFC 7523) — no per-user OAuth consent needed once the SA's Client ID is added to
    Workspace Admin -> Domain-wide delegation with GMAIL_SCOPES. Cached per subject until ~60s
    before expiry."""
    sa = _load_sa_key()
    if sa is None:
        raise GmailOAuthError(
            "Domain-wide delegation is not configured (GOOGLE_SA_KEY_FILE / GOOGLE_SA_KEY_JSON missing or invalid)",
        )
    now = time.time()
    cached = _IMPERSONATED_TOKEN_CACHE.get(subject_email)
    if cached and cached[1] - now > 60:
        return cached[0]

    def _b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    iat = int(now)
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "sub": subject_email,
        "scope": " ".join(GMAIL_SCOPES),
        "aud": sa["token_uri"],
        "iat": iat,
        "exp": iat + 3600,
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}"
        f".{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    try:
        private_key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        signature = private_key.sign(signing_input.encode(), crypto_padding.PKCS1v15(), crypto_hashes.SHA256())
    except (ValueError, TypeError) as e:
        raise GmailOAuthError(f"Invalid GOOGLE_SA_KEY private_key (could not sign JWT): {e}") from e
    jwt = f"{signing_input}.{_b64url(signature)}"

    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                sa["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": jwt,
                },
            )
    except httpx.HTTPError as e:
        raise GmailOAuthError(f"Could not reach Google token endpoint for impersonation (network): {e}") from e
    if r.status_code != 200:
        body = r.text or ""
        hint = ""
        if r.status_code == 401 or "unauthorized_client" in body.lower():
            hint = (
                " Hint: check that the service account's Client ID is added under Google Workspace "
                "Admin -> Security -> API controls -> Domain-wide delegation with scopes "
                f"{', '.join(GMAIL_SCOPES)}."
            )
        raise GmailOAuthError(
            f"Impersonation token request failed for {subject_email!r} ({r.status_code}): {body}{hint}",
        )
    try:
        data = r.json()
    except json.JSONDecodeError:
        raise GmailOAuthError("Impersonation token response was not JSON")
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise GmailOAuthError("No access_token in impersonation token response")
    try:
        ttl = float(data.get("expires_in"))
    except (TypeError, ValueError):
        ttl = 3600.0
    _IMPERSONATED_TOKEN_CACHE[subject_email] = (token, now + ttl)
    return token


def resolve_redirect_uri(public_origin: str | None) -> str:
    reload_google_env()
    fixed = os.environ.get("GOOGLE_REDIRECT_URI", "").strip() or settings.GOOGLE_REDIRECT_URI.strip()
    if fixed:
        return fixed
    if not public_origin or not str(public_origin).strip():
        raise ValueError(
            "Set GOOGLE_REDIRECT_URI in .env or pass public_origin (e.g. https://your-ui-host) "
            "so the callback URL matches Google Cloud OAuth credentials.",
        )
    return f"{public_origin.rstrip('/')}/api/oauth/google/callback"


def build_authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        },
    )
    return f"{GOOGLE_AUTH}?{q}"


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict[str, Any]:
    reload_google_env()
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        raise GmailOAuthError("Google OAuth client not configured")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise GmailOAuthError(r.text or f"token exchange failed ({r.status_code})")
    return r.json()


def refresh_access_token(mailbox_email: str | None = None) -> str:
    reload_google_env()
    if _uses_dwd(mailbox_email):
        return _impersonated_access_token((mailbox_email or "").strip())
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    refresh = google_refresh_token_value(mailbox_email)
    if not cid or not sec or not refresh:
        raise GmailOAuthError("Gmail not connected (missing client id/secret or refresh token)")
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                GOOGLE_TOKEN,
                data={
                    "refresh_token": refresh,
                    "client_id": cid,
                    "client_secret": sec,
                    "grant_type": "refresh_token",
                },
            )
    except httpx.HTTPError as e:
        raise GmailOAuthError(f"Could not reach Google token endpoint (network): {e}") from e
    if r.status_code != 200:
        body = r.text or ""
        if r.status_code in (400, 401) and (
            "invalid_grant" in body.lower() or "token has been expired" in body.lower()
        ):
            clear_google_refresh_token_if_allowed(mailbox_email)
        raise GmailOAuthError(body or f"refresh failed ({r.status_code})")
    try:
        data = r.json()
    except json.JSONDecodeError:
        raise GmailOAuthError((r.text or "")[:500] or "refresh response was not JSON")
    token = data.get("access_token")
    if not token:
        raise GmailOAuthError("no access_token in refresh response")
    return str(token)


def clear_google_refresh_token_if_allowed(mailbox_email: str | None = None) -> None:
    if not bootstrap_env_write_allowed():
        return
    creds = _mailbox_creds(mailbox_email)
    if creds["found"]:
        key = f"GMAIL_ACCOUNT__{_slug_for_mailbox((mailbox_email or '').strip())}"
        upsert_env_files_everywhere({key: ""})
    else:
        upsert_env_files_everywhere({"GOOGLE_REFRESH_TOKEN": ""})


def persist_google_refresh_token(refresh_token: str, mailbox_email: str | None = None) -> None:
    block = env_write_blocked_reason()
    if block:
        raise RuntimeError(
            "Cannot save GOOGLE_REFRESH_TOKEN. " + block + " Or add GOOGLE_REFRESH_TOKEN manually to .env and restart.",
        )
    tok = refresh_token.strip()
    em = (mailbox_email or "").strip()
    if em:
        key = f"GMAIL_ACCOUNT__{_slug_for_mailbox(em)}"
        existing = _mailbox_creds(em)
        send_as = existing["send_as"] if existing["found"] else em
        payload = json.dumps({"send_as": send_as, "refresh_token": tok}, separators=(",", ":"))
        try:
            upsert_env_files_everywhere({key: payload})
        except OSError as e:
            raise RuntimeError(
                f"Failed to write .env file on disk: {e}. Check folder permissions or Docker volume mounts.",
            ) from e
        if _mailbox_creds(em)["refresh_token"] != tok:
            raise RuntimeError(
                f"{key} was saved to disk but did not load back into this process. "
                "See env_paths_found in GET /setup/status; a later .env in the chain may be clearing the key.",
            )
        return
    try:
        upsert_env_files_everywhere({"GOOGLE_REFRESH_TOKEN": tok})
    except OSError as e:
        raise RuntimeError(
            f"Failed to write .env file on disk: {e}. Check folder permissions or Docker volume mounts.",
        ) from e
    if google_refresh_token_value() != tok:
        raise RuntimeError(
            "GOOGLE_REFRESH_TOKEN was saved to disk but did not load back into this process. "
            "See env_paths_found in GET /setup/status; a later .env in the chain may be clearing the key.",
        )


def _sanitize_rfc_subject(subject: str) -> str:
    s = (subject or "").replace("\r", " ").replace("\n", " ").strip()
    return s if s else "(no subject)"


def _friendly_gmail_api_error(body: str) -> str | None:
    """Short hint when Gmail returns SERVICE_DISABLED (API not enabled for the GCP project)."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    err = data.get("error")
    if not isinstance(err, dict):
        return None
    msg = (err.get("message") or "").strip()
    details = err.get("details") if isinstance(err.get("details"), list) else []
    activation_url = ""
    service_disabled = False
    for d in details:
        if not isinstance(d, dict):
            continue
        if d.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo":
            if (d.get("reason") or "").upper() == "SERVICE_DISABLED":
                service_disabled = True
            meta = d.get("metadata")
            if isinstance(meta, dict):
                activation_url = (meta.get("activationUrl") or "").strip()
    if service_disabled or "accessnotconfigured" in body.lower() or "has not been used in project" in msg.lower():
        parts = [
            "Gmail API is disabled for this Google Cloud project (OAuth tokens work, but gmail.googleapis.com rejects calls).",
            "Enable it: APIs & Services → Library → «Gmail API» → Enable, in the same project as your OAuth Web client.",
            "Wait a few minutes after enabling, then retry Send or Connect Gmail.",
        ]
        if activation_url:
            parts.append(f"Link: {activation_url}")
        return " ".join(parts)
    bl = body.lower()
    if "from" in bl and ("invalid" in bl or "not allowed" in bl or "precondition" in bl):
        return (
            "Gmail rejected the From address. If you set GMAIL_SEND_AS_EMAIL in .env, that address must appear under "
            "Gmail → Settings → See all settings → Accounts → Send mail as (added and verified). "
            f"Original message: {msg or 'see Events detail'}"
        )
    return None


def _raise_unless_gmail_http_ok(r: httpx.Response, *, fallback: str) -> None:
    if r.status_code == 200:
        return
    body = r.text or ""
    hint = _friendly_gmail_api_error(body)
    raise GmailOAuthError(hint or body or f"{fallback} ({r.status_code})")


def gmail_profile_email(access_token: str) -> str:
    """Mailbox address for From: — uses Gmail API (same scopes as send/modify), not userinfo.email."""
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{GMAIL_API}/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail profile failed")
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise GmailOAuthError("Gmail profile response was not valid JSON") from e
    em = str(data.get("emailAddress") or "").strip()
    if not em:
        raise GmailOAuthError("No emailAddress in Gmail profile")
    return em


def list_send_as_rows(access_token: str) -> list[dict[str, Any]]:
    """Raw SendAs rows from Gmail (includes verificationStatus, smtpMsa, etc.)."""
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{GMAIL_API}/users/me/settings/sendAs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail sendAs list failed")
    data = r.json()
    rows: list[dict[str, Any]] = []
    for row in data.get("sendAs") or []:
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_send_as_emails(access_token: str) -> list[str]:
    """Send-as addresses OK for API From: (accepted / verified; not pending)."""
    out: list[str] = []
    for row in list_send_as_rows(access_token):
        em = str(row.get("sendAsEmail") or "").strip()
        if not em:
            continue
        vs = (row.get("verificationStatus") or "accepted").lower()
        if vs in ("accepted", "verified", ""):
            out.append(em)
    return out


def summarize_send_as_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Safe subset for GET /setup/gmail-send-as-list (no secrets)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        smtp = row.get("smtpMsa")
        out.append(
            {
                "sendAsEmail": row.get("sendAsEmail"),
                "displayName": row.get("displayName"),
                "verificationStatus": row.get("verificationStatus"),
                "isDefault": row.get("isDefault"),
                "isPrimary": row.get("isPrimary"),
                "treatAsAlias": row.get("treatAsAlias"),
                "hasCustomSmtp": bool(isinstance(smtp, dict) and smtp),
            },
        )
    return out


def list_configured_mailboxes() -> list[dict[str, Any]]:
    """Per-mailbox entries currently configured in env (GMAIL_ACCOUNT__<SLUG>=<json>), for GET
    /setup/status. Does NOT include the default/global mailbox (Alexey) — that one is reported
    separately via google_client_configured()/google_refresh_token_value(None), unchanged."""
    reload_google_env()
    prefix = "GMAIL_ACCOUNT__"
    out: list[dict[str, Any]] = []
    for key in sorted(k for k in os.environ if k.startswith(prefix)):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        refresh = str(data.get("refresh_token") or "").strip()
        send_as = str(data.get("send_as") or "").strip()
        out.append(
            {
                "mailbox_email": send_as or key[len(prefix):].lower(),
                "send_as": send_as,
                "connected": bool(refresh),
            },
        )
    return out


def dwd_status() -> dict[str, Any]:
    """Domain-wide delegation status for GET /setup/status. Safe to expose: sa_client_email is a
    service-account identifier (not a secret), never the private key."""
    sa = _load_sa_key()
    return {
        "dwd_configured": sa is not None,
        "delegated_domains": sorted(_dwd_delegated_domains()),
        "sa_client_email": sa["client_email"] if sa else "",
    }


def resolve_outbound_from_mime(access_token: str, mailbox_email: str | None = None) -> tuple[str, str]:
    """
    RFC From: value for MIME, and bare mailbox address (for JSON / logs).
    Uses GMAIL_SEND_AS_EMAIL (or the per-mailbox send_as when mailbox_email resolves to one) when
    set and Gmail accepts it; adds displayName from Send as when present.

    DWD path (stage C): when _uses_dwd(mailbox_email) is True, access_token already impersonates
    mailbox_email directly — that mailbox IS the authenticated Gmail user, so there is no sendAs
    list to check (and calling it would ask the impersonated mailbox for its own aliases, which is
    pointless here). From: is simply mailbox_email itself.
    """
    reload_google_env()
    if _uses_dwd(mailbox_email):
        em = (mailbox_email or "").strip()
        return em, em
    o = str(_mailbox_creds(mailbox_email)["send_as"] or "").strip().strip('"').strip("'")
    if not o or "@" not in o:
        addr = gmail_profile_email(access_token)
        return addr, addr

    rows = list_send_as_rows(access_token)
    row = next(
        (
            r
            for r in rows
            if isinstance(r, dict) and str(r.get("sendAsEmail") or "").strip().lower() == o.lower()
        ),
        None,
    )
    if row is None:
        known = list_send_as_emails(access_token)
        preview = ", ".join(known[:15])
        more = f" (+{len(known) - 15} more)" if len(known) > 15 else ""
        raise GmailOAuthError(
            f"{o!r} (GMAIL_SEND_AS_EMAIL) is not in this account's «Send mail as» list (or spelling differs). "
            f"GET /setup/gmail-send-as-list shows what Gmail returns. Accepted-for-send aliases: {preview or '—'}{more}"
        )

    vs_raw = row.get("verificationStatus")
    vs = str(vs_raw).strip().lower() if vs_raw not in (None, "") else "accepted"
    if vs == "pending":
        raise GmailOAuthError(
            f"{o!r} is listed under «Send mail as» but Gmail still reports verificationStatus=pending — "
            "finish verification (confirmation link in email) or remove and re-add the address in Gmail settings."
        )
    if vs not in ("accepted", "verified"):
        raise GmailOAuthError(
            f"{o!r} has verificationStatus={vs_raw!r}. Gmail may block API sends with this From. "
            "Fix it in Gmail → See all settings → Accounts and import → Send mail as."
        )
    display_name = str(row.get("displayName") or "").strip()
    hdr = formataddr((display_name, o)) if display_name else o
    return hdr, o


def _build_mime_raw(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body_html: str,
    reply_to_mailbox: str | None = None,
) -> str:
    """RFC 5322 + SMTP policy; Gmail is picky about MIME structure and line endings.

    ``reply_to_mailbox``: bare email for ``Reply-To:``. With «Send mail as» aliases, Gmail can
    still deliver bounces / some auto-replies to the OAuth primary; an explicit Reply-To aimed at
    the same mailbox as the visible sender steers normal replies and many auto-responders correctly.
    """
    subj = _sanitize_rfc_subject(subject)
    plain = html_to_plain_text_for_mime(body_html) or re.sub(r"<[^>]+>", "", body_html) or ""
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"] = from_addr
    if reply_to_mailbox and "@" in reply_to_mailbox:
        msg["Reply-To"] = reply_to_mailbox.strip()
    msg["To"] = to_addr
    msg.set_content(plain, subtype="plain", charset="utf-8")
    msg.add_alternative(body_html, subtype="html", charset="utf-8")
    raw = base64.urlsafe_b64encode(msg.as_bytes(policy=SMTP)).decode()
    return raw


def gmail_send_message(
    access_token: str,
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body_html: str,
    reply_to_mailbox: str | None = None,
) -> dict[str, Any]:
    raw = _build_mime_raw(
        from_addr=from_addr,
        to_addr=to_addr,
        subject=subject,
        body_html=body_html,
        reply_to_mailbox=reply_to_mailbox,
    )
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{GMAIL_API}/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"raw": raw},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail send failed")
    return r.json()


def gmail_has_to_or_from_correspondence(access_token: str, email: str, *, max_results: int = 1) -> bool:
    """True if the mailbox has at least one message to or from this address."""
    em = (email or "").strip()
    if not em or "@" not in em:
        return False
    q = f"(to:{em} OR from:{em})"
    return bool(gmail_search_message_ids(access_token, q, max_results=max_results))


def gmail_search_message_ids(access_token: str, query: str, *, max_results: int = 5) -> list[str]:
    q = urllib.parse.urlencode({"q": query, "maxResults": str(max_results)})
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{GMAIL_API}/users/me/messages?{q}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail list failed")
    data = r.json()
    msgs = data.get("messages") or []
    return [str(m["id"]) for m in msgs if isinstance(m, dict) and m.get("id")]


def gmail_list_message_refs_paginated(
    access_token: str,
    query: str,
    *,
    max_per_page: int = 100,
) -> list[dict[str, str]]:
    """
    All message ids matching query (paginated). Each item: {"id", "threadId"} (threadId may be missing).
    """
    out: list[dict[str, str]] = []
    page_token: str | None = None
    with httpx.Client(timeout=60.0) as client:
        while True:
            params: dict[str, str] = {"q": query, "maxResults": str(min(max_per_page, 500))}
            if page_token:
                params["pageToken"] = page_token
            qstr = urllib.parse.urlencode(params)
            r = client.get(
                f"{GMAIL_API}/users/me/messages?{qstr}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            _raise_unless_gmail_http_ok(r, fallback="gmail list messages failed")
            data = r.json()
            for m in data.get("messages") or []:
                if not isinstance(m, dict) or not m.get("id"):
                    continue
                out.append(
                    {
                        "id": str(m["id"]),
                        "threadId": str(m["threadId"]) if m.get("threadId") else "",
                    },
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return out


def gmail_get_message_full(access_token: str, message_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=60.0) as client:
        r = client.get(
            f"{GMAIL_API}/users/me/messages/{message_id}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail get message failed")
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise GmailOAuthError("Gmail message response was not JSON") from e


def gmail_get_thread_full(access_token: str, thread_id: str) -> dict[str, Any]:
    """Full thread resource including all messages (format=full)."""
    tid = (thread_id or "").strip()
    if not tid:
        raise GmailOAuthError("thread id is empty")
    with httpx.Client(timeout=120.0) as client:
        r = client.get(
            f"{GMAIL_API}/users/me/threads/{tid}",
            params={"format": "full"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail get thread failed")
    try:
        return r.json()
    except json.JSONDecodeError as e:
        raise GmailOAuthError("Gmail thread response was not JSON") from e


def normalize_rfc_message_id_header(raw: str | None) -> str | None:
    """Strip angle brackets and whitespace for comparisons."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("<") and s.endswith(">") and len(s) > 2:
        s = s[1:-1].strip()
    return s if s else None


def gmail_message_rfc_id_from_full_json(json_msg: dict[str, Any]) -> str | None:
    """Read Message-ID from a messages.get JSON (format=full)."""
    payload = json_msg.get("payload")
    if not isinstance(payload, dict):
        return None
    headers_raw = payload.get("headers")
    if not isinstance(headers_raw, list):
        return None
    for h in headers_raw:
        if not isinstance(h, dict):
            continue
        if str(h.get("name") or "").strip().lower() == "message-id":
            return normalize_rfc_message_id_header(str(h.get("value") or ""))
    return None


def verify_gmail_roundtrip_with_code(code: str, redirect_uri: str, mailbox_email: str | None = None) -> None:
    """Exchange code, send test mail to self, confirm it appears in mailbox; persist refresh on
    success. ``mailbox_email``, when set, persists the refresh token under that mailbox's
    GMAIL_ACCOUNT__<SLUG> key instead of the global GOOGLE_REFRESH_TOKEN (B-071 stage B connect
    flow) — the self-test itself still uses today's default send-as resolution."""
    tokens = exchange_code_for_tokens(code, redirect_uri)
    refresh = (tokens.get("refresh_token") or "").strip()
    access = (tokens.get("access_token") or "").strip()
    if not access:
        raise GmailOAuthError("No access_token from Google (cannot run verification)")

    profile = gmail_profile_email(access)
    from_hdr, from_mailbox = resolve_outbound_from_mime(access)
    gmail_send_message(
        access,
        from_addr=from_hdr,
        reply_to_mailbox=from_mailbox,
        to_addr=profile,
        subject=VERIFY_SUBJECT,
        body_html=f"<p>{VERIFY_BODY_TEXT}</p>",
    )
    # Gmail search can lag a few seconds after send; retry before failing the OAuth callback.
    found: list[str] = []
    query = f'subject:"{VERIFY_SUBJECT}"'
    for attempt in range(20):
        found = gmail_search_message_ids(access, query)
        if found:
            break
        time.sleep(1.0)
    if not found:
        raise GmailOAuthError(
            "Verification failed: sent test message but Gmail search did not return it after ~20s "
            "(indexing delay or search quota). Retry Connect Gmail once.",
        )
    if not refresh:
        raise GmailOAuthError(
            "No refresh_token returned — revoke the app under Google Account → Security → Third-party access, "
            "then connect again with prompt=consent.",
        )
    persist_google_refresh_token(refresh, mailbox_email)


def send_mime_gmail(
    *,
    to_email: str,
    subject: str,
    body_html: str,
    attachments: list[dict[str, Any]] | None,
    mailbox_email: str | None = None,
    inline_images: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    access = refresh_access_token(mailbox_email)
    from_hdr, from_addr = resolve_outbound_from_mime(access, mailbox_email)
    subj = _sanitize_rfc_subject(subject)
    msg = EmailMessage()
    msg["Subject"] = subj
    msg["From"] = from_hdr
    if from_addr and "@" in from_addr:
        msg["Reply-To"] = from_addr.strip()
    msg["To"] = to_email.strip()
    plain = html_to_plain_text_for_mime(body_html) or re.sub(r"<[^>]+>", "", body_html) or ""
    msg.set_content(plain, subtype="plain", charset="utf-8")
    msg.add_alternative(body_html, subtype="html", charset="utf-8")
    if inline_images:
        html_part = msg.get_payload()[-1]
        for img in inline_images:
            if not isinstance(img, dict):
                continue
            cid = str(img.get("cid") or "")
            content = img.get("content") if isinstance(img.get("content"), (bytes, bytearray)) else b""
            mt = str(img.get("mime_type") or "application/octet-stream")
            main_t, _sep, sub_t = mt.partition("/")
            main_t = main_t or "application"
            sub_t = sub_t or "octet-stream"
            html_part.add_related(
                bytes(content),
                main_t,
                sub_t,
                cid=f"<{cid}>",
                filename=str(img.get("filename") or cid),
                disposition="inline",
            )
    for att in attachments or []:
        if not isinstance(att, dict):
            continue
        fn = str(att.get("filename") or "attachment")
        content = att.get("content") if isinstance(att.get("content"), (bytes, bytearray)) else b""
        mt = str(att.get("mime_type") or "application/octet-stream")
        main_t, _sep, sub_t = mt.partition("/")
        main_t = main_t or "application"
        sub_t = sub_t or "octet-stream"
        msg.add_attachment(
            bytes(content),
            maintype=main_t,
            subtype=sub_t,
            filename=fn,
        )
    raw = base64.urlsafe_b64encode(msg.as_bytes(policy=SMTP)).decode()
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{GMAIL_API}/users/me/messages/send",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            json={"raw": raw},
        )
    _raise_unless_gmail_http_ok(r, fallback="gmail send failed")
    data = r.json()
    mid = data.get("id")
    rfc_mid: str | None = None
    if mid:
        try:
            full = gmail_get_message_full(access, str(mid))
            rfc_mid = gmail_message_rfc_id_from_full_json(full)
        except (GmailOAuthError, httpx.HTTPError, TypeError, ValueError):
            rfc_mid = None
    return {
        "provider_message_id": mid,
        "thread_id": data.get("threadId") or mid,
        "provider": "gmail",
        "accepted": True,
        "from_email": from_addr,
        "to_email": to_email,
        "subject": subj,
        "rfc_message_id": rfc_mid,
    }


def send_html_via_gmail(
    *,
    to_email: str,
    subject: str,
    body_html: str,
    mailbox_email: str | None = None,
) -> dict[str, Any]:
    access = refresh_access_token(mailbox_email)
    from_hdr, from_mailbox = resolve_outbound_from_mime(access, mailbox_email)
    data = gmail_send_message(
        access,
        from_addr=from_hdr,
        reply_to_mailbox=from_mailbox,
        to_addr=to_email.strip(),
        subject=subject,
        body_html=body_html,
    )
    mid = data.get("id")
    rfc_mid: str | None = None
    if mid:
        try:
            full = gmail_get_message_full(access, str(mid))
            rfc_mid = gmail_message_rfc_id_from_full_json(full)
        except (GmailOAuthError, httpx.HTTPError, TypeError, ValueError):
            rfc_mid = None
    return {
        "provider_message_id": mid,
        "thread_id": data.get("threadId") or mid,
        "provider": "gmail",
        "accepted": True,
        "from_email": from_mailbox,
        "to_email": to_email,
        "subject": _sanitize_rfc_subject(subject),
        "rfc_message_id": rfc_mid,
    }
