"""Review Contacts tab buckets — must match `contactReviewTabBucket` in AiBizOsHumanUI.jsx."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.models.contact import Contact

ReviewBucketName = Literal["pending", "approved", "rejected", "bounced", "dead_mailbox", "no_email"]

ALL_REVIEW_BUCKETS: tuple[str, ...] = (
    "pending",
    "approved",
    "rejected",
    "bounced",
    "dead_mailbox",
    "no_email",
)


def review_bucket_for_contact_row(c: Contact) -> str:
    """Same rules as frontend: delivery health → usable email → review_status."""
    em = (c.email or "").strip().lower()
    has_usable = "@" in em
    if c.email_health == "dead_mailbox":
        return "dead_mailbox"
    if c.email_health == "bounced":
        return "bounced"
    if not has_usable:
        return "no_email"
    rs = c.review_status or "pending"
    if rs == "pending":
        return "pending"
    if rs == "rejected":
        return "rejected"
    if rs in ("approved", "edited"):
        return "approved"
    return "no_email"


def review_counts_from_contacts(contacts: list[Contact]) -> dict[str, int]:
    out = {k: 0 for k in ALL_REVIEW_BUCKETS}
    for c in contacts:
        b = review_bucket_for_contact_row(c)
        if b in out:
            out[b] += 1
    return out


def filter_contacts_by_review_bucket(contacts: list[Contact], bucket: str) -> list[Contact]:
    if bucket not in ALL_REVIEW_BUCKETS:
        return contacts
    return [c for c in contacts if review_bucket_for_contact_row(c) == bucket]
