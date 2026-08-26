"""Surname sanity-check against the contact's own LinkedIn URL (B-275).

Apollo occasionally returns a corrupted last name while every other field is right: the Gardens
Interactive contact arrived as "Stephen Gamescom" with the correct title and a verified
`stephen@gardens.dev`, while the `linkedin_url` in the same Apollo row (`in/sbellgardens`) says the
person is Stephen Bell. Only the fact that our emails address people by first name kept that out of
the wave — in a subject line or a signature it would have been a letter to a person who does not
exist.

The check is mechanical and one-directional: we never "fix" the name, we only flag a contact whose
surname cannot be found in its own LinkedIn slug so a human confirms it before generation. A slug
that carries no name information at all (``in/j-4b21f9``) is not evidence of anything and never
raises the flag.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Suffixes that are not part of the surname and must not be checked against the slug.
_NAME_SUFFIXES: frozenset[str] = frozenset({"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba"})

# Marketing/duty noise Apollo sometimes appends to a name ("Stephen Gamescom", "Anna We're hiring").
_MIN_SURNAME_LEN = 3

FLAG_KEY = "surname_unverified"
NOTE_KEY = "surname_check_note"


def _slug_from_linkedin(url: str | None) -> str:
    """LinkedIn profile URL -> its letters-only slug ('in/sbell-gardens' -> 'sbellgardens')."""
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith("http"):
        u = "https://" + u
    try:
        parsed = urlparse(u)
    except ValueError:
        return ""
    if "linkedin." not in (parsed.netloc or "").lower():
        return ""
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return ""
    # .../in/<slug> — take the segment after 'in' when present, else the last segment.
    slug = parts[parts.index("in") + 1] if "in" in parts and len(parts) > parts.index("in") + 1 else parts[-1]
    return re.sub(r"[^a-z]", "", slug.lower())


def _name_parts(name: str | None) -> tuple[str, str]:
    """(first, last) in lowercase letters only. Last is '' when the name has no usable surname."""
    tokens = [re.sub(r"[^a-zа-яё]", "", t.lower()) for t in (name or "").split()]
    tokens = [t for t in tokens if t and t not in _NAME_SUFFIXES]
    if len(tokens) < 2:
        return (tokens[0] if tokens else "", "")
    return tokens[0], tokens[-1]


def surname_matches_linkedin(name: str | None, linkedin_url: str | None) -> bool | None:
    """Is the contact's surname present in its own LinkedIn slug?

    ``True``  — the surname appears in the slug (or the slug is a Cyrillic/transliterated case we
                cannot judge, treated as agreement rather than as a false alarm).
    ``False`` — the slug carries name information (it contains the first name, or is long enough to
                be a human-readable handle) but not the surname → the surname is suspect.
    ``None``  — nothing checkable: no LinkedIn URL, no surname, or an opaque slug.
    """
    slug = _slug_from_linkedin(linkedin_url)
    first, last = _name_parts(name)
    if not slug or not last or len(last) < _MIN_SURNAME_LEN:
        return None
    if not last.isascii():
        return None  # Cyrillic surname vs a latin slug — transliteration, not a mismatch
    if last in slug:
        return True
    # The slug must actually carry name information before its silence about the surname counts as
    # evidence: either it contains the first name, or it is a readable handle (initial + surname
    # style, as in 'sbellgardens') rather than an opaque id.
    if first and first in slug:
        return False
    if len(slug) >= 8:
        return False
    return None


def annotate_surname_check(contact: dict[str, Any]) -> dict[str, Any]:
    """Flag a contact dict in place when its surname disagrees with its LinkedIn slug (B-275).

    Sets ``surname_unverified`` + a human-readable note; both travel into ``source_json`` on persist
    and are cleared when a human edits the contact (update_contact_fields)."""
    if not isinstance(contact, dict):
        return contact
    verdict = surname_matches_linkedin(contact.get("name"), contact.get("linkedin"))
    if verdict is False:
        contact[FLAG_KEY] = True
        contact[NOTE_KEY] = (
            f"Фамилия в имени «{contact.get('name')}» не совпадает с профилем "
            f"{contact.get('linkedin')} — сверь имя вручную перед генерацией письма (B-275)."
        )
    return contact


def contact_surname_unverified(source_json: dict[str, Any] | None) -> bool:
    """Read the flag back from a persisted contact's source payload."""
    return bool(isinstance(source_json, dict) and source_json.get(FLAG_KEY))
