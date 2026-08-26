import re

# B-138: quote-stripping — cut the quoted email history out of a reply BEFORE classification.
# Our own CAN-SPAM opt-out signature ("...reply "STOP" and I'll take you off my list.") is nearly
# always echoed back verbatim when a contact hits reply-all, so classifying the raw body would read
# our own canned "STOP" as the contact's opt-out (any reply, including "sounds great, let's talk",
# would be misread as unsubscribe and the contact permanently banned). Structural markers cover the
# common quoting styles (Gmail/Outlook/Apple Mail); the signature-fingerprint scan is a backstop for
# clients that top-post without any marker line at all.
_QUOTE_LINE_RE = re.compile(r"^\s{0,3}>")
_ON_WROTE_RE = re.compile(r"^\s{0,3}On\s.+\swrote:\s*$", re.IGNORECASE)
_ORIGINAL_MESSAGE_RE = re.compile(r"^\s{0,3}-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE)
_FROM_HEADER_RE = re.compile(r"^\s{0,3}From:\s", re.IGNORECASE)
_SENT_OR_SUBJECT_HEADER_RE = re.compile(r"^\s{0,3}(Sent|To|Subject):\s", re.IGNORECASE | re.MULTILINE)

# A contact never types these phrases themselves — they're our own canned opt-out wording (B-128
# signatures), so their presence anywhere in the body means it's quoted, even with no ">" prefix.
_OUR_SIGNATURE_FINGERPRINTS = [
    re.compile(r"reply\s+[\"'“]?stop[\"'”]?\s+and", re.IGNORECASE),
    re.compile(r"take (?:me|you) off (?:my|our|this) list", re.IGNORECASE),
]


def strip_quoted_reply(body: str) -> str:
    """Return only the new text of a reply, with quoted email history cut off."""
    lines = (body or "").splitlines()
    cut_at = len(lines)
    for i, line in enumerate(lines):
        if _QUOTE_LINE_RE.match(line) or _ON_WROTE_RE.match(line) or _ORIGINAL_MESSAGE_RE.match(line):
            cut_at = i
            break
        if _FROM_HEADER_RE.match(line):
            lookahead = "\n".join(lines[i : i + 4])
            if _SENT_OR_SUBJECT_HEADER_RE.search(lookahead):
                cut_at = i
                break
    for i, line in enumerate(lines[:cut_at]):
        if any(p.search(line) for p in _OUR_SIGNATURE_FINGERPRINTS):
            cut_at = i
            break
    return "\n".join(lines[:cut_at]).strip()


# CAN-SPAM opt-out (B-128 Phase 1b): reply-based unsubscribe, checked BEFORE not_interested so a
# "no thanks, please stop emailing me" reply routes to suppression, not just a closed thread.
# Word-boundary regexes avoid false positives on substrings (e.g. "nonstop growth" must not match).
_UNSUBSCRIBE_PATTERNS = [
    re.compile(r"\bunsubscribe\b"),
    re.compile(r"\bstop\b"),
    re.compile(r"\bremove me\b"),
    re.compile(r"\btake me off\b"),
    re.compile(r"\bopt[\s-]?out\b"),
]

# B-138: checked BEFORE interested, and BEFORE that plain substring "interested" check, so
# "not interested" isn't swallowed by the fact that it contains the substring "interested".
# The first pattern allows a few words between "not" and "interested" (e.g. "not really interested",
# "not particularly interested") — word-boundary regexes, same style as _UNSUBSCRIBE_PATTERNS above.
_NOT_INTERESTED_PATTERNS = [
    re.compile(r"\bnot\b(?:\s+\w+){0,3}\s+interested\b"),
    re.compile(r"\bno thanks\b"),
    re.compile(r"\bpass\b"),
]


def classify_reply(body: str) -> dict | None:
    """Classify a reply's NEW text (quoted history stripped first, see strip_quoted_reply above).
    Returns None — not a guess — when nothing is left after stripping."""
    stripped = strip_quoted_reply(body)
    if not stripped:
        return None
    text = stripped.lower()

    if any(p.search(text) for p in _UNSUBSCRIBE_PATTERNS):
        return {
            "label": "unsubscribe",
            "confidence": "high",
            "reason": "opt-out intent keywords",
        }

    if any(p.search(text) for p in _NOT_INTERESTED_PATTERNS):
        return {
            "label": "not_interested",
            "confidence": "high",
            "reason": "negative intent keywords",
        }

    if any(x in text for x in ["interested", "let's talk", "sounds good", "tell me more"]):
        return {
            "label": "interested",
            "confidence": "high",
            "reason": "positive intent keywords",
        }

    if any(x in text for x in ["later", "not now", "follow up"]):
        return {
            "label": "ask_later",
            "confidence": "medium",
            "reason": "delay intent",
        }

    if any(x in text for x in ["more info", "details", "send more"]):
        return {
            "label": "need_more_info",
            "confidence": "medium",
            "reason": "request for more info",
        }

    return {
        "label": "unclear",
        "confidence": "low",
        "reason": "no clear signal",
    }
