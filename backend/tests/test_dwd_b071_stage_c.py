"""B-071 stage C (domain-wide delegation) — SA key parsing, JWT-bearer impersonation, and the
credential-resolution order in refresh_access_token/resolve_outbound_from_mime.

HARD INVARIANT under test throughout: without GOOGLE_SA_KEY_FILE/GOOGLE_SA_KEY_JSON configured,
every function in gmail_oauth behaves exactly as in stage B (test_multi_mailbox_b071.py) — the DWD
branch never fires. And even with DWD fully configured, Alexey's own mailbox (mailbox_email is
None, or equals the global GMAIL_SEND_AS_EMAIL) never resolves through impersonation.

Isolation follows test_multi_mailbox_b071.py: reload_google_env()/peek_env_key_from_files() are
stubbed so tests never touch the real backend/.env, and all GOOGLE_*/GMAIL_* env vars are cleared
before each test. Module-level SA-key/token caches are also reset (they are plain dicts on the
gmail_oauth module, so a previous test's cached key/token would otherwise leak into the next).
"""

from __future__ import annotations

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import gmail_oauth as go

# ---------------------------------------------------------------------------------------------
# Isolation from the real backend/.env + module-level caches
# ---------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_gmail_env(monkeypatch):
    monkeypatch.setattr(go, "reload_google_env", lambda: None)
    monkeypatch.setattr(go, "peek_env_key_from_files", lambda key: "")
    for k in list(os.environ):
        if k.startswith("GOOGLE_") or k.startswith("GMAIL_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(go, "_SA_KEY_CACHE", None)
    monkeypatch.setattr(go, "_SA_KEY_CACHE_SOURCE", None)
    monkeypatch.setattr(go, "_IMPERSONATED_TOKEN_CACHE", {})


@pytest.fixture()
def sa_keypair():
    """A throwaway RSA keypair + the SA JSON key dict built from it (never touches real Google creds)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = key.public_key()
    sa_json = {
        "client_email": "sa-test@project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return {"private_key_obj": key, "public_key_obj": public_key, "sa_json": sa_json}


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
    """Stand-in for httpx.Client(...) used as a context manager; delegates POSTs to a responder."""

    def __init__(self, responder):
        self._responder = responder

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, data=None, **kwargs):
        return self._responder(url, data)


def _raise_if_httpx_called(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("httpx.Client should not have been constructed on this path")

    monkeypatch.setattr(go.httpx, "Client", _boom)


# ---------------------------------------------------------------------------------------------
# _load_sa_key / _dwd_configured / _dwd_eligible
# ---------------------------------------------------------------------------------------------


def test_load_sa_key_none_when_unconfigured():
    assert go._load_sa_key() is None
    assert go._dwd_configured() is False


def test_load_sa_key_from_inline_json(monkeypatch, sa_keypair):
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", json.dumps(sa_keypair["sa_json"]))
    parsed = go._load_sa_key()
    assert parsed["client_email"] == "sa-test@project.iam.gserviceaccount.com"
    assert parsed["token_uri"] == "https://oauth2.googleapis.com/token"
    assert go._dwd_configured() is True


def test_load_sa_key_file_takes_priority_over_json(monkeypatch, tmp_path, sa_keypair):
    file_key = dict(sa_keypair["sa_json"])
    file_key["client_email"] = "from-file@project.iam.gserviceaccount.com"
    key_path = tmp_path / "sa-key.json"
    key_path.write_text(json.dumps(file_key))
    monkeypatch.setenv("GOOGLE_SA_KEY_FILE", str(key_path))
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", json.dumps(sa_keypair["sa_json"]))
    parsed = go._load_sa_key()
    assert parsed["client_email"] == "from-file@project.iam.gserviceaccount.com"


def test_load_sa_key_missing_file_returns_none(monkeypatch):
    monkeypatch.setenv("GOOGLE_SA_KEY_FILE", "/nonexistent/path/sa-key.json")
    assert go._load_sa_key() is None


def test_load_sa_key_invalid_json_returns_none(monkeypatch):
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", "not-json")
    assert go._load_sa_key() is None


def test_load_sa_key_missing_required_fields_returns_none(monkeypatch):
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", json.dumps({"client_email": "sa@x.com"}))
    assert go._load_sa_key() is None


def test_dwd_eligible_requires_both_sa_and_domain(monkeypatch, sa_keypair):
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", json.dumps(sa_keypair["sa_json"]))
    monkeypatch.setenv("GOOGLE_DWD_DELEGATED_DOMAINS", "alexstaff.agency")
    assert go._dwd_eligible("stepan@alexstaff.agency") is True
    assert go._dwd_eligible("someone@othercompany.com") is False


def test_dwd_eligible_false_without_sa_even_if_domain_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_DWD_DELEGATED_DOMAINS", "alexstaff.agency")
    assert go._dwd_eligible("stepan@alexstaff.agency") is False


# ---------------------------------------------------------------------------------------------
# Resolution order — refresh_access_token / _uses_dwd
# ---------------------------------------------------------------------------------------------


def _configure_dwd(monkeypatch, sa_keypair, domains="alexstaff.agency"):
    monkeypatch.setenv("GOOGLE_SA_KEY_JSON", json.dumps(sa_keypair["sa_json"]))
    monkeypatch.setenv("GOOGLE_DWD_DELEGATED_DOMAINS", domains)


def test_order_a_alexey_none_mailbox_skips_dwd_even_when_configured(monkeypatch, sa_keypair):
    """(a) mailbox_email=None -> global refresh, DWD never invoked even though SA+domain configured."""
    _configure_dwd(monkeypatch, sa_keypair)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "alexey-refresh")
    monkeypatch.setenv("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency")

    def _spy(*a, **k):
        raise AssertionError("_impersonated_access_token must not be called for Alexey's mailbox")

    monkeypatch.setattr(go, "_impersonated_access_token", _spy)
    monkeypatch.setattr(
        go.httpx, "Client", lambda timeout=None: _FakeClient(lambda url, data: _FakeResp(json_data={"access_token": "global-tok"}))
    )
    assert go.refresh_access_token(None) == "global-tok"


def test_order_a_alexey_explicit_mailbox_equal_to_global_send_as_skips_dwd(monkeypatch, sa_keypair):
    """(a) mailbox_email explicitly equal to GMAIL_SEND_AS_EMAIL -> same as None, DWD skipped."""
    _configure_dwd(monkeypatch, sa_keypair)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "alexey-refresh")
    monkeypatch.setenv("GMAIL_SEND_AS_EMAIL", "alex@alexstaff.agency")

    def _spy(*a, **k):
        raise AssertionError("_impersonated_access_token must not be called for Alexey's mailbox")

    monkeypatch.setattr(go, "_impersonated_access_token", _spy)
    monkeypatch.setattr(
        go.httpx, "Client", lambda timeout=None: _FakeClient(lambda url, data: _FakeResp(json_data={"access_token": "global-tok"}))
    )
    assert go.refresh_access_token("alex@alexstaff.agency") == "global-tok"
    assert go._uses_dwd("alex@alexstaff.agency") is False


def test_order_b_per_mailbox_entry_skips_dwd_even_when_domain_eligible(monkeypatch, sa_keypair):
    """(b) mailbox has its own GMAIL_ACCOUNT__<SLUG> entry -> uses that refresh token, DWD skipped."""
    _configure_dwd(monkeypatch, sa_keypair)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv(
        "GMAIL_ACCOUNT__STEPAN_ALEXSTAFF_AGENCY",
        json.dumps({"send_as": "stepan@alexstaff.agency", "refresh_token": "stepan-token"}),
    )

    def _spy(*a, **k):
        raise AssertionError("_impersonated_access_token must not be called when a per-mailbox entry exists")

    monkeypatch.setattr(go, "_impersonated_access_token", _spy)
    monkeypatch.setattr(
        go.httpx, "Client", lambda timeout=None: _FakeClient(lambda url, data: _FakeResp(json_data={"access_token": "stepan-tok"}))
    )
    assert go.refresh_access_token("stepan@alexstaff.agency") == "stepan-tok"
    assert go._uses_dwd("stepan@alexstaff.agency") is False


def test_order_c_domain_mailbox_without_per_mailbox_key_uses_dwd(monkeypatch, sa_keypair):
    """(c) domain-eligible mailbox, no GMAIL_ACCOUNT__ entry, SA configured -> DWD impersonation."""
    _configure_dwd(monkeypatch, sa_keypair)
    assert go._uses_dwd("newhire@alexstaff.agency") is True

    monkeypatch.setattr(go, "_impersonated_access_token", lambda subject: f"impersonated-{subject}")
    _raise_if_httpx_called(monkeypatch)  # the normal refresh_token grant must not run
    assert go.refresh_access_token("newhire@alexstaff.agency") == "impersonated-newhire@alexstaff.agency"


def test_order_d_domain_mailbox_without_sa_key_falls_back_to_global(monkeypatch):
    """(d) no GOOGLE_SA_KEY_FILE/_JSON at all -> stage B behavior, even for a would-be delegated domain."""
    monkeypatch.setenv("GOOGLE_DWD_DELEGATED_DOMAINS", "alexstaff.agency")  # domain listed, but no SA key
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "alexey-refresh")

    assert go._uses_dwd("newhire@alexstaff.agency") is False

    def _spy(*a, **k):
        raise AssertionError("_impersonated_access_token must not be called without an SA key")

    monkeypatch.setattr(go, "_impersonated_access_token", _spy)
    monkeypatch.setattr(
        go.httpx, "Client", lambda timeout=None: _FakeClient(lambda url, data: _FakeResp(json_data={"access_token": "global-tok"}))
    )
    assert go.refresh_access_token("newhire@alexstaff.agency") == "global-tok"


def test_whole_suite_inert_without_sa_key_matches_stage_b(monkeypatch):
    """Invariant: with no GOOGLE_SA_KEY_FILE/_JSON, _uses_dwd is False for every input — stage B
    behavior is untouched regardless of GOOGLE_DWD_DELEGATED_DOMAINS."""
    monkeypatch.setenv("GOOGLE_DWD_DELEGATED_DOMAINS", "alexstaff.agency,example.com")
    assert go._uses_dwd(None) is False
    assert go._uses_dwd("stepan@alexstaff.agency") is False
    assert go._uses_dwd("random@example.com") is False


# ---------------------------------------------------------------------------------------------
# resolve_outbound_from_mime — DWD path returns mailbox_email itself, no sendAs lookup
# ---------------------------------------------------------------------------------------------


def test_resolve_outbound_from_mime_dwd_path_returns_mailbox_email_without_sendas_lookup(monkeypatch, sa_keypair):
    _configure_dwd(monkeypatch, sa_keypair)

    def _boom(*a, **k):
        raise AssertionError("list_send_as_rows must not be called on the DWD path")

    monkeypatch.setattr(go, "list_send_as_rows", _boom)
    hdr, addr = go.resolve_outbound_from_mime("access-tok", "newhire@alexstaff.agency")
    assert hdr == "newhire@alexstaff.agency"
    assert addr == "newhire@alexstaff.agency"


def test_resolve_outbound_from_mime_alexey_path_unchanged_when_dwd_configured(monkeypatch, sa_keypair):
    """Even with DWD fully configured, Alexey's own resolution (mailbox_email=None) is untouched:
    it still falls through to gmail_profile_email when no GMAIL_SEND_AS_EMAIL is set."""
    _configure_dwd(monkeypatch, sa_keypair)
    monkeypatch.setattr(go, "gmail_profile_email", lambda access_token: "alex@alexstaff.agency")
    hdr, addr = go.resolve_outbound_from_mime("access-tok")
    assert addr == "alex@alexstaff.agency"
    assert hdr == "alex@alexstaff.agency"


# ---------------------------------------------------------------------------------------------
# _impersonated_access_token — JWT construction/signing, caching, error hints
# ---------------------------------------------------------------------------------------------


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def test_impersonated_access_token_builds_and_signs_a_valid_jwt(monkeypatch, sa_keypair):
    _configure_dwd(monkeypatch, sa_keypair)
    captured = {}

    def _responder(url, data):
        captured["url"] = url
        captured["data"] = data
        return _FakeResp(json_data={"access_token": "minted-token", "expires_in": 3600})

    monkeypatch.setattr(go.httpx, "Client", lambda timeout=None: _FakeClient(_responder))

    token = go._impersonated_access_token("newhire@alexstaff.agency")

    assert token == "minted-token"
    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert captured["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    jwt = captured["data"]["assertion"]
    header_b64, claims_b64, sig_b64 = jwt.split(".")
    header = json.loads(_b64url_decode(header_b64))
    claims = json.loads(_b64url_decode(claims_b64))
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == sa_keypair["sa_json"]["client_email"]
    assert claims["sub"] == "newhire@alexstaff.agency"
    assert claims["scope"] == " ".join(go.GMAIL_SCOPES)
    assert claims["exp"] == claims["iat"] + 3600

    # Signature verifies against the keypair's public key.
    signing_input = f"{header_b64}.{claims_b64}".encode()
    signature = _b64url_decode(sig_b64)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    sa_keypair["public_key_obj"].verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())


def test_impersonated_access_token_caches_per_subject(monkeypatch, sa_keypair):
    _configure_dwd(monkeypatch, sa_keypair)
    call_count = {"n": 0}

    def _responder(url, data):
        call_count["n"] += 1
        return _FakeResp(json_data={"access_token": f"tok-{call_count['n']}", "expires_in": 3600})

    monkeypatch.setattr(go.httpx, "Client", lambda timeout=None: _FakeClient(_responder))

    first = go._impersonated_access_token("newhire@alexstaff.agency")
    second = go._impersonated_access_token("newhire@alexstaff.agency")
    assert first == second == "tok-1"
    assert call_count["n"] == 1


def test_impersonated_access_token_without_sa_key_raises():
    with pytest.raises(go.GmailOAuthError, match="Domain-wide delegation is not configured"):
        go._impersonated_access_token("newhire@alexstaff.agency")


def test_impersonated_access_token_401_gives_dwd_hint(monkeypatch, sa_keypair):
    _configure_dwd(monkeypatch, sa_keypair)
    monkeypatch.setattr(
        go.httpx,
        "Client",
        lambda timeout=None: _FakeClient(lambda url, data: _FakeResp(status_code=401, text="unauthorized_client")),
    )
    with pytest.raises(go.GmailOAuthError, match="Domain-wide delegation"):
        go._impersonated_access_token("newhire@alexstaff.agency")


# ---------------------------------------------------------------------------------------------
# dwd_status() — GET /setup/status payload
# ---------------------------------------------------------------------------------------------


def test_dwd_status_unconfigured():
    status = go.dwd_status()
    assert status == {"dwd_configured": False, "delegated_domains": [], "sa_client_email": ""}


def test_dwd_status_configured(monkeypatch, sa_keypair):
    _configure_dwd(monkeypatch, sa_keypair, domains="alexstaff.agency, example.com")
    status = go.dwd_status()
    assert status["dwd_configured"] is True
    assert status["delegated_domains"] == ["alexstaff.agency", "example.com"]
    assert status["sa_client_email"] == "sa-test@project.iam.gserviceaccount.com"
