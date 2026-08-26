"""Offline tests for the verification ladder (syntax + MX + provider), DNS/provider monkeypatched."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import app.services.email_verification_service as ev
from app.services.email_verification_service import (
    CATCH_ALL,
    DEAD,
    RISKY,
    TTL_DAYS,
    UNKNOWN,
    UNKNOWN_TTL_DAYS,
    VALID,
    _is_fresh,
    verify_email_address,
)


def test_syntax_dead(monkeypatch):
    # Bad syntax fails before any DNS.
    assert verify_email_address("notanemail")[0] == DEAD
    assert verify_email_address("a@b")[0] == DEAD  # no dot in domain


def test_bad_domain_dead(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: False)
    verdict, source = verify_email_address("someone@dead-domain.com")
    assert verdict == DEAD
    assert source == "mx"


def test_mx_ok_no_provider_is_unknown(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "", raising=False)
    verdict, source = verify_email_address("someone@gmail.com")
    assert verdict == UNKNOWN
    assert source == "mx"


def test_provider_valid(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "millionverifier", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(ev, "_provider_verdict", lambda e, p, k, t: VALID)
    assert verify_email_address("real@company.com") == (VALID, "millionverifier")


def test_provider_dead_blocks(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "millionverifier", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(ev, "_provider_verdict", lambda e, p, k, t: DEAD)
    # Valid MX, provider says the mailbox is dead.
    assert verify_email_address("dead-mailbox@example.com") == (DEAD, "millionverifier")


def test_provider_risky(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "zerobounce", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(ev, "_provider_verdict", lambda e, p, k, t: RISKY)
    assert verify_email_address("catchall@company.com")[0] == RISKY


def test_provider_millionverifier_catch_all_is_non_blocking_verdict(monkeypatch):
    # B-013 §2: catch-all is common on real corporate domains and must not block — MillionVerifier's
    # "catch_all" result now maps to CATCH_ALL (not RISKY, which used to be treated as a hold).
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "millionverifier", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)

    class _Resp:
        def json(self):
            return {"result": "catch_all"}

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "get", lambda *a, **k: _Resp())
    verdict, source = verify_email_address("someone@bigcorp.com")
    assert verdict == CATCH_ALL
    assert source == "millionverifier"


def test_provider_zerobounce_catch_all_is_non_blocking_verdict(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "zerobounce", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)

    class _Resp:
        def json(self):
            return {"status": "catch-all"}

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "get", lambda *a, **k: _Resp())
    verdict, source = verify_email_address("someone@bigcorp.com")
    assert verdict == CATCH_ALL


def test_provider_unknown_result_maps_to_unknown_not_risky(monkeypatch):
    monkeypatch.setattr(ev, "_has_mx", lambda domain, timeout: True)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_PROVIDER", "millionverifier", raising=False)
    monkeypatch.setattr(ev.settings, "EMAIL_VERIFIER_API_KEY", "test-key", raising=False)

    class _Resp:
        def json(self):
            return {"result": "unknown"}

    import httpx as _httpx

    monkeypatch.setattr(_httpx, "get", lambda *a, **k: _Resp())
    verdict, _ = verify_email_address("someone@bigcorp.com")
    assert verdict == UNKNOWN


def test_is_fresh_unknown_uses_short_ttl():
    # B-013 §8: UNKNOWN used to be treated as never-fresh (permanent DNS re-check every tick).
    just_now = SimpleNamespace(
        email_verified_at=datetime.utcnow(), email_verification_status=UNKNOWN,
    )
    assert _is_fresh(just_now) is True

    stale_unknown = SimpleNamespace(
        email_verified_at=datetime.utcnow() - timedelta(days=UNKNOWN_TTL_DAYS, hours=1),
        email_verification_status=UNKNOWN,
    )
    assert _is_fresh(stale_unknown) is False


def test_is_fresh_valid_uses_long_ttl():
    fresh_valid = SimpleNamespace(
        email_verified_at=datetime.utcnow() - timedelta(days=UNKNOWN_TTL_DAYS, hours=1),
        email_verification_status=VALID,
    )
    # Older than the UNKNOWN ttl but well within the normal TTL_DAYS — still fresh.
    assert _is_fresh(fresh_valid) is True

    stale_valid = SimpleNamespace(
        email_verified_at=datetime.utcnow() - timedelta(days=TTL_DAYS, hours=1),
        email_verification_status=VALID,
    )
    assert _is_fresh(stale_valid) is False


def test_is_fresh_no_timestamp_is_never_fresh():
    assert _is_fresh(SimpleNamespace(email_verified_at=None, email_verification_status=VALID)) is False
