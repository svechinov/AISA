import json
import logging
import re

import httpx

from app.config import settings
from app.services.env_bootstrap import LLM_KEY_BY_PROVIDER, VALID_LLM

logger = logging.getLogger(__name__)

__all__ = ["generate_json", "parse_json_text", "complete_prompt_json_object", "llm_configured"]

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
OPENAI_API = "https://api.openai.com/v1/chat/completions"
PERPLEXITY_API = "https://api.perplexity.ai/chat/completions"
XAI_API = "https://api.x.ai/v1/chat/completions"

HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)


def _stub_master_variant_a() -> dict[str, str]:
    return {
        "subject": "Quick note — possible fit",
        "body": (
            "We are writing with a focused reason to connect: there is a plausible overlap between "
            "what you are building and an initiative we are running now.\n\n"
            "In practical terms, we can explain the fit in a short call or share a tight written "
            "summary — whichever you prefer — and we will keep jargon to a minimum.\n\n"
            "If this is useful, reply with one line about the best next step; if not, feel free to "
            "ignore and we will not follow up repeatedly.\n\n"
            "Thanks for your time."
        ),
    }


def _stub_master_variant_b() -> dict[str, str]:
    return {
        "subject": "Timing check on a narrow partnership angle",
        "body": (
            "I want to see whether this week is a sensible moment for a short conversation about a "
            "specific partnership angle.\n\n"
            "The background is straightforward: we line up a small set of counterparties where the fit "
            "is testable without a long procurement cycle.\n\n"
            "You can steer the format — written bullets first or a brief call — and we will keep the "
            "first exchange lightweight.\n\n"
            "If the topic is not relevant, a quick “pass” is enough; we will not re-litigate by email.\n\n"
            "Appreciated either way."
        ),
    }


def _stub_master_variant_c() -> dict[str, str]:
    return {
        "subject": "Direct note — working together",
        "body": (
            "This email is intentionally direct: we are deciding whether to include your organization "
            "in a short list for a concrete pilot.\n\n"
            "The pilot has a bounded scope, a clear success signal, and no open-ended “explore” phase "
            "without a decision point.\n\n"
            "If you want to qualify in or out, tell us what evidence would help on your side and we "
            "will mirror that level of detail.\n\n"
            "If you already know this is not a priority, one line is sufficient — we will stop there.\n\n"
            "We can also share a one-page scope note if that is easier than a live conversation on the first pass.\n\n"
            "Best regards"
        ),
    }


def parse_json_text(text: str) -> dict:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON returned by model: {e}") from e

    if not isinstance(parsed, dict):
        raise ValueError("Model output must be a JSON object")

    return parsed


def _strip_markdown_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*)\n?```\s*$", t, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t


def _coerce_json_dict_from_text(text: str) -> dict:
    raw = _strip_markdown_fences(text or "")
    try:
        return parse_json_text(raw)
    except ValueError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return parse_json_text(raw[start : end + 1])
        raise ValueError(
            f"Model did not return a JSON object. First 400 chars: {raw[:400]!r}"
        ) from None


def _provider_priority_order() -> list[str]:
    raw = (settings.LLM_PROVIDER_PRIORITY or "").strip()
    seen: set[str] = set()
    order: list[str] = []
    for p in raw.split(","):
        pid = p.strip().lower()
        if pid in VALID_LLM and pid not in seen:
            seen.add(pid)
            order.append(pid)
    for pid in LLM_KEY_BY_PROVIDER:
        if pid not in seen:
            order.append(pid)
    return order


def _api_key_for(provider_id: str) -> str:
    field = LLM_KEY_BY_PROVIDER.get(provider_id)
    if not field:
        return ""
    return (getattr(settings, field, None) or "").strip()


def _any_llm_key() -> bool:
    for pid in LLM_KEY_BY_PROVIDER:
        if _api_key_for(pid):
            return True
    return False


def llm_configured() -> bool:
    """True if at least one LLM provider API key is set."""
    return _any_llm_key()


def _content_openai_style(data: dict) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError(f"Unexpected chat response: {data!r}"[:800])
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    raise ValueError(f"No message content in response: {data!r}"[:800])


def _anthropic_complete(prompt: str, api_key: str) -> str:
    model = (settings.ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022").strip()
    payload = {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        r = client.post(
            ANTHROPIC_API,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )
    if r.status_code >= 400:
        raise ValueError(f"Anthropic HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    blocks = data.get("content") or []
    texts: list[str] = []
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                texts.append(b.get("text") or "")
    out = "".join(texts).strip()
    if not out:
        raise ValueError(f"Anthropic returned no text: {data!r}"[:600])
    return out


def _openai_chat_complete(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    json_mode: bool,
) -> str:
    payload: dict = {
        "model": model,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    def post(body: dict):
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            return client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json=body,
            )

    r = post(payload)
    if r.status_code == 400 and json_mode and "response_format" in payload:
        del payload["response_format"]
        r = post(payload)
    if r.status_code >= 400:
        raise ValueError(f"Chat API HTTP {r.status_code} ({url}): {r.text[:500]}")
    return _content_openai_style(r.json())


def _complete_with_fallback(prompt: str) -> str:
    errors: list[str] = []
    for name in _provider_priority_order():
        key = _api_key_for(name)
        if not key:
            continue
        try:
            if name == "claude":
                text_out = _anthropic_complete(prompt, key)
            elif name == "openai":
                model = (settings.OPENAI_MODEL or "gpt-4o").strip()
                text_out = _openai_chat_complete(
                    OPENAI_API,
                    key,
                    model,
                    prompt,
                    json_mode=True,
                )
            elif name == "perplexity":
                model = (settings.PERPLEXITY_MODEL or "sonar").strip()
                text_out = _openai_chat_complete(
                    PERPLEXITY_API,
                    key,
                    model,
                    prompt,
                    json_mode=False,
                )
            elif name == "grok":
                model = (settings.XAI_MODEL or "grok-2-latest").strip()
                text_out = _openai_chat_complete(
                    XAI_API,
                    key,
                    model,
                    prompt,
                    json_mode=False,
                )
            else:
                continue
            logger.info("LLM completion OK provider=%s", name)
            return text_out
        except Exception as e:
            msg = f"{name}: {e}"
            logger.warning("LLM provider failed: %s", msg)
            errors.append(msg)
            continue
    detail = "; ".join(errors) if errors else "no provider keys configured"
    raise ValueError(f"All LLM providers failed ({detail})")


def _stub_outreach_emails() -> dict:
    return {
        "emails": [
            {
                "company": "Acme Corp",
                "to": "contact@acme.example",
                "subject": "Outreach — Acme Corp",
                "body": "Hi,\n\nShort note relevant to your organization.\n\nBest regards",
            }
        ]
    }


def generate_json(prompt: str, model: str = "stub", task_kind: str | None = None) -> dict:
    """
    Structured JSON generation. Live APIs are used for companies/contacts (and emails / master when keys exist),
    in LLM_PROVIDER_PRIORITY order. Stubs remain only when no API keys (master_email / legacy email path).
    """
    if task_kind == "master_email":
        if _any_llm_key():
            raw = _complete_with_fallback(prompt)
            return _coerce_json_dict_from_text(raw)
        a, b, c = _stub_master_variant_a(), _stub_master_variant_b(), _stub_master_variant_c()
        return {"variants": [a, b, c]}

    prompt_lower = prompt.lower()

    if '"emails"' in prompt_lower or "outreach email" in prompt_lower:
        if _any_llm_key():
            raw = _complete_with_fallback(prompt)
            return _coerce_json_dict_from_text(raw)
        return _stub_outreach_emails()

    if (
        '"contacts"' in prompt_lower
        or "decision makers" in prompt_lower
        or "target roles" in prompt_lower
    ):
        if not _any_llm_key():
            raise ValueError(
                "No LLM API keys configured. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY "
                "(see backend/.env.example and LLM_PROVIDER_PRIORITY)."
            )
        raw = _complete_with_fallback(prompt)
        return _coerce_json_dict_from_text(raw)

    if '"companies"' in prompt_lower:
        if not _any_llm_key():
            raise ValueError(
                "No LLM API keys configured. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY."
            )
        raw = _complete_with_fallback(prompt)
        return _coerce_json_dict_from_text(raw)

    raise ValueError(
        "LLM prompt did not match a known workflow step (companies / contacts / emails). "
        "Check prompt_builder output."
    )


def complete_prompt_json_object(prompt: str) -> dict:
    """
    General-purpose JSON object completion (classification, short extracts).
    Caller supplies the full prompt and JSON schema instructions.
    """
    if not _any_llm_key():
        raise ValueError(
            "No LLM API keys configured. Set at least one of: "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY."
        )
    raw = _complete_with_fallback(prompt)
    return _coerce_json_dict_from_text(raw)
