"""Email-address deliverability check before send.

Ladder: syntax -> domain MX lookup (free, local DNS) -> paid provider API (only if a key is set).
MX-only catches dead/typo'd domains; it cannot confirm an individual mailbox (that is what tripped
AXLEBOLT: valid Google MX, dead mailbox). A provider (MillionVerifier/ZeroBounce) is required to catch
dead mailboxes — until a key is configured we run MX-only and leave the verdict 'unknown' (which the
gate lets through). Only a hard 'dead' (bad syntax/domain, or provider = invalid) blocks a send.

Verdicts written to contacts.email_verification_status: valid | catch_all | risky | dead | unknown.
Only `dead` blocks a send (see app/services/contactability.py) — catch_all and unknown are common
on legitimate corporate domains (the provider can't confirm one mailbox on a domain that accepts
everything) and must not withhold a real lead; `risky` is kept for a future provider verdict that
is genuinely a confirmed-bad signal short of dead, and also does not block today (decision
2026-07-08, see docs/AI-Biz-OS-backlog.md).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.utils.email_normalize import email_domain, normalize_email

_log = logging.getLogger(__name__)

VALID = "valid"
CATCH_ALL = "catch_all"
RISKY = "risky"
DEAD = "dead"
UNKNOWN = "unknown"

#: Verdicts that never block a send — see module docstring.
NON_BLOCKING = frozenset({VALID, CATCH_ALL, RISKY, UNKNOWN})

TTL_DAYS = 30
#: Unknown verdicts (no provider key, or a provider call that failed) get a short TTL so a newly
#: configured provider key — or a since-recovered DNS/network hiccup — is picked up quickly,
#: without re-hitting DNS on every single worker tick (was: never cached, see backlog B-013 §8).
UNKNOWN_TTL_DAYS = 1

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _syntax_ok(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def _domain_of(email: str) -> str:
    return email_domain(email)


def _has_mx(domain: str, timeout: float) -> bool | None:
    """True/False if resolvable, None if DNS itself failed (inconclusive → do not hard-fail).

    TODO(B-013 §10): duplicates MX resolution against `hardcore_osint.get_mx_record` (different
    timeout handling, no A-record fallback there, returns a hostname instead of tri-state) — that
    function feeds a separate SMTP-probe cache in workers/contacts_worker.py and touching it is
    out of scope for this pass. Worth a shared MX helper later; not unified now to avoid risking
    the OSINT discovery pipeline for a low-priority cleanup.
    """
    if not domain:
        return False
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        try:
            answers = resolver.resolve(domain, "MX")
            if len(answers) > 0:
                return True
        except dns.resolver.NoAnswer:
            # No MX — some domains accept mail on the A record; treat A as deliverable.
            answers = resolver.resolve(domain, "A")
            return len(answers) > 0
        return False
    except (ImportError,) as e:  # dnspython missing — cannot check, inconclusive
        _log.warning("MX check unavailable: %s", e)
        return None
    except Exception as e:  # NXDOMAIN, timeout, etc.
        name = type(e).__name__
        if name in ("NXDOMAIN", "NoNameservers"):
            return False
        _log.info("MX check inconclusive for %s: %s", domain, name)
        return None


def _provider_verdict(email: str, provider: str, api_key: str, timeout: float) -> str:
    """Call the configured verifier. Returns a verdict; UNKNOWN on any error (never blocks blindly)."""
    provider = (provider or "").strip().lower()
    try:
        import httpx

        if provider == "millionverifier":
            r = httpx.get(
                "https://api.millionverifier.com/api/v3/",
                params={"api": api_key, "email": email, "timeout": int(timeout)},
                timeout=timeout,
            )
            data = r.json()
            result = str(data.get("result", "")).lower()
            return {
                "ok": VALID,
                "invalid": DEAD,
                "disposable": DEAD,
                "catch_all": CATCH_ALL,
            }.get(result, UNKNOWN)

        if provider == "zerobounce":
            r = httpx.get(
                "https://api.zerobounce.net/v2/validate",
                params={"api_key": api_key, "email": email},
                timeout=timeout,
            )
            status = str(r.json().get("status", "")).lower()
            return {
                "valid": VALID,
                "invalid": DEAD,
                "catch-all": CATCH_ALL,
                "do_not_mail": DEAD,
                "spamtrap": DEAD,
            }.get(status, UNKNOWN)

        _log.warning("Unknown email verifier provider: %s", provider)
        return UNKNOWN
    except Exception:
        _log.exception("email verifier call failed (provider=%s)", provider)
        return UNKNOWN


def verify_email_address(email: str) -> tuple[str, str]:
    """Return (verdict, source) for an address. Network only, no DB. Never raises."""
    e = normalize_email(email)
    if not _syntax_ok(e):
        return DEAD, "syntax"

    timeout = float(getattr(settings, "EMAIL_VERIFIER_HTTP_TIMEOUT_SEC", 20.0))
    mx = _has_mx(_domain_of(e), timeout)
    if mx is False:
        return DEAD, "mx"

    provider = (getattr(settings, "EMAIL_VERIFIER_PROVIDER", "") or "").strip()
    api_key = (getattr(settings, "EMAIL_VERIFIER_API_KEY", "") or "").strip()
    if provider and api_key:
        return _provider_verdict(e, provider, api_key, timeout), provider

    # MX-only path: domain resolves (or DNS inconclusive) but no mailbox-level check available.
    return UNKNOWN, "mx"


def _is_fresh(contact) -> bool:
    ts = getattr(contact, "email_verified_at", None)
    if not ts:
        return False
    status = getattr(contact, "email_verification_status", "unknown") or "unknown"
    # Unknown gets a short TTL (not "never fresh"): a provider key may have been added since, or a
    # DNS hiccup may have cleared — but the default no-provider path always yields UNKNOWN for a
    # valid-MX domain, so treating it as permanently stale re-ran a live DNS lookup on every single
    # worker tick for every due item (backlog B-013 §8).
    ttl_days = UNKNOWN_TTL_DAYS if status == UNKNOWN else TTL_DAYS
    return ts >= datetime.utcnow() - timedelta(days=ttl_days)


def verify_and_apply_for_contact(db: Session, contact, *, force: bool = False) -> str:
    """Verify the contact's email, persist the verdict, and handle a dead verdict.

    Dead → suppression + a find-replacement research task (reusing the dead-mailbox path). Returns
    the verdict. Cached within TTL_DAYS unless force=True. Best-effort: never raises to the caller.
    """
    if contact is None or not (getattr(contact, "email", "") or "").strip():
        return UNKNOWN
    if not force and _is_fresh(contact):
        return contact.email_verification_status or UNKNOWN

    verdict, source = verify_email_address(contact.email)
    contact.email_verification_status = verdict
    contact.email_verified_at = datetime.utcnow()
    contact.email_verification_source = source
    db.add(contact)
    db.commit()

    if verdict == DEAD:
        _handle_dead_address(db, contact)
    return verdict


def _handle_dead_address(db: Session, contact) -> None:
    from app.repositories.research_task_repo import create_research_task, find_pending_replacement_task
    from app.repositories.contact_repo import find_replacement_contact_for_source
    from app.repositories.suppression_repo import add_suppression
    from app.services.research_task_input import build_find_replacement_input_json

    try:
        add_suppression(db, contact.email, reason="dead_mailbox", source_run_id=contact.run_id,
                        note="pre-send verification: address dead")
        replacement_exists = find_replacement_contact_for_source(db, contact.run_id, contact.id)
        if not find_pending_replacement_task(db, contact.run_id, contact.id) and not replacement_exists:
            create_research_task(
                db=db,
                run_id=contact.run_id,
                contact_id=contact.id,
                company=contact.company,
                task_type="find_replacement_email",
                status="open",
                reason="verification_dead",
                input_json=build_find_replacement_input_json(contact),
                output_json={},
            )
    except Exception:
        _log.exception("handling dead address for contact %s failed", getattr(contact, "id", None))
