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
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

HTTP_TIMEOUT = httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0)

# B-371: Anthropic's prompt cache only kicks in above a ~1024-token prefix (claude-opus-4-8 /
# claude-sonnet-5); below that a cache_control marker is a no-op, so short prefixes are just
# concatenated into the prompt as before.
_MIN_CACHE_PREFIX_CHARS = 4000

# --- Task tiering: task_kind -> tier -> provider model. Unmarked tasks default to "standard".
# Only tiers that differ from the default are listed; discovery/dossier/translation etc. stay standard.
TASK_TIER: dict[str, str] = {
    # strong: quality drives reply rate — outreach reasoning/draft + the email critic
    "outreach_reasoning": "strong",
    "outreach_draft": "strong",
    "single_outreach": "strong",
    "email_critic": "strong",
    # B-018: instruct-edit rewrites a finalized email minimally — same quality bar as drafting
    "draft_instruct_edit": "strong",
    # cheap: mechanical JSON extraction/classification
    "apollo_hints": "cheap",
    "company_source_extract": "cheap",
    "inbound_delivery_classify": "cheap",
    "thread_delivery_classify": "cheap",
    "program_match": "cheap",
    "osint_entity_extract": "cheap",
    "osint_email_permutations": "cheap",
    # B-063: mechanical NER (list job titles named in a draft) for the named-role cross-check —
    # extraction only, no judgement, same tier as the other mechanical JSON tasks above.
    "role_ner_extract": "cheap",
    # research (Perplexity-first) is intentionally EMPTY for now: every current OSINT task analyses a
    # corpus already gathered by search_service, so a web-grounded model adds little and sonar's JSON
    # mode is unreliable. The tier + provider ordering stay wired below — enabling a real web-discovery
    # task later is a one-line addition here.
}
# Providers moved to the front of the priority order for a given tier.
_TIER_PREFERRED_PROVIDER: dict[str, str] = {
    "cheap": "gemini",
    "research": "perplexity",
}


def _tier_for(task_kind: str | None) -> str:
    return TASK_TIER.get(task_kind or "", "standard")


def _model_for(provider_id: str, tier: str) -> str:
    if provider_id == "claude":
        if tier == "strong":
            return (settings.ANTHROPIC_MODEL_STRONG or settings.ANTHROPIC_MODEL or "claude-sonnet-5").strip()
        if tier == "cheap":
            return (settings.ANTHROPIC_MODEL_CHEAP or settings.ANTHROPIC_MODEL or "claude-haiku-4-5").strip()
        return (settings.ANTHROPIC_MODEL or "claude-sonnet-5").strip()
    if provider_id == "gemini":
        return (settings.GEMINI_MODEL or "gemini-flash-latest").strip()
    if provider_id == "openai":
        return (settings.OPENAI_MODEL or "gpt-4o").strip()
    if provider_id == "perplexity":
        return (settings.PERPLEXITY_MODEL or "sonar").strip()
    if provider_id == "grok":
        return (settings.XAI_MODEL or "grok-2-latest").strip()
    if provider_id == "kimi":
        return (settings.KIMI_MODEL or "kimi-k2.7-code").strip()
    return ""


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


def _provider_priority_order(tier: str = "standard") -> list[str]:
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
    preferred = _TIER_PREFERRED_PROVIDER.get(tier)
    if preferred and preferred in order:
        order = [preferred] + [p for p in order if p != preferred]
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


def _anthropic_style_complete(
    url: str,
    headers: dict,
    prompt: str,
    model: str,
    cache_prefix: str | None = None,
    *,
    log_label: str = "Anthropic",
) -> str:
    """Shared body for any provider speaking the Anthropic Messages API shape (request payload +
    `content[].type=="text"` response parsing) — today that's Claude itself and Kimi via Ollama
    Cloud's Anthropic-compatible endpoint (B-372). Caller supplies the url/headers, so auth
    (x-api-key vs. Bearer) stays provider-specific without duplicating the request/parse logic."""
    if cache_prefix and len(cache_prefix) >= _MIN_CACHE_PREFIX_CHARS:
        content = [
            {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": prompt},
        ]
    else:
        content = (cache_prefix + prompt) if cache_prefix else prompt
    payload = {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": content}],
    }
    proxy = settings.HTTP_PROXY.strip()
    with httpx.Client(timeout=HTTP_TIMEOUT, proxy=proxy if proxy else None) as client:
        r = client.post(url, headers=headers, json=payload)
    if r.status_code >= 400:
        raise ValueError(f"{log_label} HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    blocks = data.get("content") or []
    texts: list[str] = []
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                texts.append(b.get("text") or "")
    out = "".join(texts).strip()
    if not out:
        raise ValueError(f"{log_label} returned no text: {data!r}"[:600])
    # B-371 acceptance criterion: watch cache_read_input_tokens climb over the following week.
    usage = data.get("usage") or {}
    logger.info(
        "%s cache: model=%s write=%s read=%s input=%s",
        log_label,
        model,
        usage.get("cache_creation_input_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("input_tokens"),
    )
    return out


def _anthropic_complete(prompt: str, api_key: str, model: str, cache_prefix: str | None = None) -> str:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    return _anthropic_style_complete(
        ANTHROPIC_API, headers, prompt, model, cache_prefix=cache_prefix, log_label="Anthropic"
    )


def _kimi_complete(prompt: str, api_key: str, model: str, cache_prefix: str | None = None) -> str:
    """Kimi via Ollama Cloud's Anthropic-compatible endpoint (B-372): same request/response shape
    as Claude, but Bearer auth (no x-api-key) and no prompt-cache support — Ollama Cloud may not
    honor cache_control, so cache_prefix is always glued onto prompt as a plain string here, same
    as the non-Anthropic providers, rather than sent as a cacheable block."""
    url = settings.OLLAMA_ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    full_prompt = (cache_prefix + prompt) if cache_prefix else prompt
    return _anthropic_style_complete(url, headers, full_prompt, model, log_label="Kimi")


def _gemini_complete(prompt: str, api_key: str, model: str, *, json_mode: bool) -> str:
    url = f"{GEMINI_API_BASE}/{model}:generateContent"
    gen_config: dict = {"temperature": 0.2}
    if json_mode:
        gen_config["responseMimeType"] = "application/json"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    proxy = settings.HTTP_PROXY.strip()
    with httpx.Client(timeout=HTTP_TIMEOUT, proxy=proxy if proxy else None) as client:
        r = client.post(
            url,
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
            json=payload,
        )
    if r.status_code >= 400:
        raise ValueError(f"Gemini HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {data!r}"[:600])
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    texts = [p.get("text") or "" for p in parts if isinstance(p, dict)]
    out = "".join(texts).strip()
    if not out:
        raise ValueError(f"Gemini returned no text: {data!r}"[:600])
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
        proxy = settings.HTTP_PROXY.strip()
        with httpx.Client(timeout=HTTP_TIMEOUT, proxy=proxy if proxy else None) as client:
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


def _complete_with_fallback(prompt: str, tier: str = "standard", cache_prefix: str | None = None) -> dict:
    """Try providers in tier order; return the parsed JSON object from the first that succeeds.

    JSON coercion happens inside the loop so an unparseable response counts as a provider failure
    and falls through to the next provider — essential for cheap/research tiers where a non-Claude
    provider is tried first (e.g. Perplexity's sonar has no reliable JSON mode).

    `cache_prefix` (B-371): a stable prompt prefix eligible for Anthropic prompt caching. Only the
    Claude branch can act on it (cache_control marker); every other provider just gets it glued
    back onto the front of `prompt` so their behavior is unchanged.
    """
    errors: list[str] = []
    for name in _provider_priority_order(tier):
        key = _api_key_for(name)
        if not key:
            continue
        model = _model_for(name, tier)
        try:
            if name == "claude":
                text_out = _anthropic_complete(prompt, key, model, cache_prefix=cache_prefix)
            elif name == "gemini":
                text_out = _gemini_complete(
                    (cache_prefix + prompt) if cache_prefix else prompt, key, model, json_mode=True
                )
            elif name == "openai":
                text_out = _openai_chat_complete(
                    OPENAI_API,
                    key,
                    model,
                    (cache_prefix + prompt) if cache_prefix else prompt,
                    json_mode=True,
                )
            elif name == "perplexity":
                text_out = _openai_chat_complete(
                    PERPLEXITY_API,
                    key,
                    model,
                    (cache_prefix + prompt) if cache_prefix else prompt,
                    json_mode=False,
                )
            elif name == "grok":
                text_out = _openai_chat_complete(
                    XAI_API,
                    key,
                    model,
                    (cache_prefix + prompt) if cache_prefix else prompt,
                    json_mode=False,
                )
            elif name == "kimi":
                text_out = _kimi_complete(prompt, key, model, cache_prefix=cache_prefix)
            else:
                continue
            result = _coerce_json_dict_from_text(text_out)
            logger.info("LLM completion OK provider=%s model=%s tier=%s", name, model, tier)
            return result
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


def generate_json(
    prompt: str,
    model: str = "stub",
    task_kind: str | None = None,
    cache_prefix: str | None = None,
) -> dict:
    """
    Structured JSON generation. Live APIs are used for companies/contacts (and emails / master when keys exist),
    in tier-aware provider order (see TASK_TIER). Stubs remain only when no API keys (master_email / legacy email path).

    `cache_prefix` (B-371): stable prompt prefix eligible for Anthropic prompt caching — see
    `_complete_with_fallback`.
    """
    tier = _tier_for(task_kind)

    if task_kind == "master_email":
        if _any_llm_key():
            return _complete_with_fallback(prompt, tier, cache_prefix=cache_prefix)
        a, b, c = _stub_master_variant_a(), _stub_master_variant_b(), _stub_master_variant_c()
        return {"variants": [a, b, c]}

    if task_kind == "followup_draft":
        # Live-only: the follow-up prompt matches none of the content markers below, so without an
        # explicit branch it would raise (caller falls back to a template). With a key it now
        # generates a real draft (still manually reviewed before send).
        if not _any_llm_key():
            raise ValueError("No LLM API keys configured (followup_draft).")
        return _complete_with_fallback(prompt, tier, cache_prefix=cache_prefix)

    if task_kind in ("single_outreach", "outreach_reasoning", "outreach_draft"):
        if _any_llm_key():
            return _complete_with_fallback(prompt, tier, cache_prefix=cache_prefix)
        if task_kind == "outreach_reasoning":
            return {
                "hook": (
                    "Concrete fit between the recipient’s stated role and the campaign’s target profile."
                ),
                "angle": "connect via their stated priority / recent activity",
                "problem": "a likely bottleneck implied by their role and context",
                "solution": "one bounded Quick Win step with a clear success signal",
                "cta_type": "a short 15-minute call",
                "key_point": "whether a brief scoping exchange is worth scheduling this week",
            }
        return {
            "subject": "Quick note — relevant to your team",
            "body": (
                "Hi,\n\n"
                "I’m reaching out because this aligns with your organization and the campaign we’re running — "
                "not a generic blast.\n\n"
                "If a short exchange or a one-page outline would help you decide, we can keep it lightweight "
                "and specific to your context.\n\n"
                "If the timing is off, a one-line pass is enough — we will not push repeated follow-ups.\n\n"
                "Best regards"
            ),
        }

    prompt_lower = prompt.lower()

    if '"emails"' in prompt_lower or "outreach email" in prompt_lower:
        if _any_llm_key():
            return _complete_with_fallback(prompt, tier)
        return _stub_outreach_emails()

    if (
        '"contacts"' in prompt_lower
        or "decision makers" in prompt_lower
        or "target roles" in prompt_lower
    ):
        if not _any_llm_key():
            raise ValueError(
                "No LLM API keys configured. Set at least one of: "
                "ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY "
                "(see backend/.env.example and LLM_PROVIDER_PRIORITY)."
            )
        return _complete_with_fallback(prompt, tier)

    if '"companies"' in prompt_lower:
        if not _any_llm_key():
            raise ValueError(
                "No LLM API keys configured. Set at least one of: "
                "ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY."
            )
        return _complete_with_fallback(prompt, tier)

    raise ValueError(
        "LLM prompt did not match a known workflow step (companies / contacts / emails). "
        "Check prompt_builder output."
    )


def complete_prompt_json_object(
    prompt: str, task_kind: str | None = None, cache_prefix: str | None = None
) -> dict:
    """
    General-purpose JSON object completion (classification, short extracts).
    Caller supplies the full prompt and JSON schema instructions; task_kind selects the model tier.

    `cache_prefix` (B-371): stable prompt prefix eligible for Anthropic prompt caching — see
    `_complete_with_fallback`.
    """
    if not _any_llm_key():
        raise ValueError(
            "No LLM API keys configured. Set at least one of: "
            "ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, XAI_API_KEY."
        )
    return _complete_with_fallback(prompt, _tier_for(task_kind), cache_prefix=cache_prefix)
