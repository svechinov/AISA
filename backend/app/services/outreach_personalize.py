"""Shared outreach copy helpers: master variants validation, salutation strip, per-contact send."""

from __future__ import annotations

import random
import re
from typing import Any, Protocol

from app.services.template_renderer import personalize_outreach_text

_LEADING_SALUTATION = re.compile(
    r"^\s*(?:hi|hello|hey|dear(?:\s+team|\s+there)?)\s*[,.!]?\s*\n*",
    re.IGNORECASE,
)

MASTER_VARIANT_COUNT = 3

_VARIANT_MIN_BODY_LENGTH_SPREAD = 50


def normalize_text_for_dedup(t: str) -> str:
    """Collapse near-duplicate bodies (order/periphrasis) for similarity checks."""
    t = t.lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    words = t.split()
    words = [w[:5] for w in words]
    return " ".join(words).strip()


_LEADING_BODY_GREETING = re.compile(r"^(hi|hello)\b", re.IGNORECASE)


class _ContactLike(Protocol):
    id: int
    company: str | None
    website: str | None
    name: str | None
    role: str | None
    email: str | None


def validate_master_email(email: dict[str, Any]) -> None:
    subj = (email.get("subject") or "").strip()
    body = (email.get("body") or "").strip()
    if not subj or not body:
        raise ValueError("Invalid master email: missing subject or body")
    if len(body) < 200:
        raise ValueError("Email too short")
    if len(body) > 2000:
        raise ValueError("Email too long")


def normalize_variants_payload(data: dict[str, Any]) -> list[dict[str, str]]:
    """Validate LLM/fallback shape: exactly three distinct, valid emails."""
    if "variants" not in data or not isinstance(data["variants"], list):
        raise ValueError("Invalid variants")
    raw = data["variants"]
    if len(raw) < 1:
        raise ValueError("Invalid variants")
    if len(raw) != MASTER_VARIANT_COUNT:
        raise ValueError(f"Expected {MASTER_VARIANT_COUNT} variants, got {len(raw)}")

    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid variant at index {i}")
        s = (item.get("subject") or "").strip()
        b = (item.get("body") or "").strip()
        validate_master_email({"subject": s, "body": b})
        out.append({"subject": s, "body": b})

    subjects = [v["subject"].strip().lower() for v in out]
    if len(set(subjects)) < len(subjects):
        raise ValueError("Subjects not unique")

    normalized_bodies = [normalize_text_for_dedup(v["body"]) for v in out]
    if len(set(normalized_bodies)) < len(normalized_bodies):
        raise ValueError("Variants too similar")

    pairs = [
        normalize_text_for_dedup(f'{v["subject"]} {v["body"]}')
        for v in out
    ]
    if len(set(pairs)) < len(pairs):
        raise ValueError("Variants too similar overall")

    lengths = [len(v["body"]) for v in out]
    if max(lengths) - min(lengths) < _VARIANT_MIN_BODY_LENGTH_SPREAD:
        raise ValueError("Variants too similar in length")

    if any(_LEADING_BODY_GREETING.match(v["body"].strip()) for v in out):
        raise ValueError("Greeting inside body")

    return out


def rng_for_contact(run_id: int, contact_id: int) -> random.Random:
    return random.Random((int(run_id) * 1_000_003) ^ int(contact_id))


def select_variant_for_contact(
    run_id: int,
    contact_id: int,
    variants: list[dict[str, str]],
) -> tuple[dict[str, str], int]:
    if not variants:
        raise ValueError("No variants to choose from")
    rng = rng_for_contact(run_id, contact_id)
    variant_idx = rng.randrange(len(variants))
    return variants[variant_idx], variant_idx


def strip_leading_salutation(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t2, n = _LEADING_SALUTATION.subn("", t, count=1)
    return t2.lstrip() if n else t


def personalize_outbound(
    run_id: int,
    contact: _ContactLike,
    master_subject: str,
    master_body: str,
) -> tuple[str, str]:
    variables = {
        "company": contact.company or "",
        "website": contact.website or "",
        "name": contact.name or "",
        "role": contact.role or "",
        "email": contact.email or "",
    }
    subject = personalize_outreach_text((master_subject or "").strip(), variables).strip()

    core = strip_leading_salutation(master_body)
    core = personalize_outreach_text(core, variables).strip()

    greeting = f"Hi {contact.name}," if (contact.name or "").strip() else "Hi,"
    body = f"{greeting}\n\n{core}"
    return subject, body
