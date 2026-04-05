"""Short plaintext previews for list endpoints (avoid shipping full HTML bodies in JSON)."""

from __future__ import annotations

import re

# List/search snippets only — full body for Human UI uses include_body=1 on GET /email-drafts/run/:id
LIST_BODY_PREVIEW_MAX = 4000


def email_body_preview_text(body: str | None, *, max_len: int = LIST_BODY_PREVIEW_MAX) -> str:
    """Plaintext preview for list rows: keep paragraph breaks; do not ship full HTML."""
    if not body:
        return ""
    text = re.sub(r"<style[\s\S]*?</style>", " ", body, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text, flags=re.IGNORECASE)
    lines = []
    for line in text.split("\n"):
        lines.append(re.sub(r"[ \t]+", " ", line).strip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
