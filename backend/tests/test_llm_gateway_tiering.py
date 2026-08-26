"""LLM gateway tiering: task_kind -> tier -> provider/model routing, fallback, and the followup fix.

Fully offline (0 tokens): every provider-level completion is monkeypatched to record the
provider+model it was asked to use and return canned JSON.
"""

import json

import pytest

import app.services.llm_gateway as gw


@pytest.fixture()
def all_keys(monkeypatch):
    """Make every provider look configured, with the full priority order."""
    monkeypatch.setattr(gw, "_api_key_for", lambda name: f"k-{name}")
    monkeypatch.setattr(
        gw.settings, "LLM_PROVIDER_PRIORITY", "claude,gemini,openai,perplexity,grok"
    )


def _record(monkeypatch, *, gemini_returns=None):
    """Patch the three transport fns; record the winning provider+model. gemini_returns overrides
    what the Gemini adapter yields (e.g. invalid JSON to exercise fallback)."""
    seen: dict[str, str] = {}
    ok = json.dumps({"ok": True})

    def anthropic(prompt, api_key, model, cache_prefix=None):
        seen.update(provider="claude", model=model)
        return ok

    def gemini(prompt, api_key, model, *, json_mode):
        seen.update(provider="gemini", model=model)
        return gemini_returns if gemini_returns is not None else ok

    url_to_provider = {
        gw.OPENAI_API: "openai",
        gw.PERPLEXITY_API: "perplexity",
        gw.XAI_API: "grok",
    }

    def openai_style(url, api_key, model, prompt, *, json_mode):
        seen.update(provider=url_to_provider[url], model=model)
        return ok

    monkeypatch.setattr(gw, "_anthropic_complete", anthropic)
    monkeypatch.setattr(gw, "_gemini_complete", gemini)
    monkeypatch.setattr(gw, "_openai_chat_complete", openai_style)
    return seen


def test_strong_tier_uses_opus(all_keys, monkeypatch):
    seen = _record(monkeypatch)
    out = gw.complete_prompt_json_object("p", task_kind="email_critic")
    assert out == {"ok": True}
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL_STRONG


def test_standard_default_uses_sonnet(all_keys, monkeypatch):
    seen = _record(monkeypatch)
    gw.complete_prompt_json_object("p")  # no task_kind -> standard
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL


def test_unknown_task_kind_defaults_standard(all_keys, monkeypatch):
    seen = _record(monkeypatch)
    gw.complete_prompt_json_object("p", task_kind="nonexistent_kind")
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL


def test_cheap_tier_prefers_gemini(all_keys, monkeypatch):
    seen = _record(monkeypatch)
    gw.complete_prompt_json_object("p", task_kind="program_match")
    assert seen["provider"] == "gemini"
    assert seen["model"] == gw.settings.GEMINI_MODEL


def test_provider_ordering_by_tier(all_keys):
    # research is intentionally unmapped (empty) for now, but the ordering mechanism must stay wired:
    # research -> perplexity first, cheap -> gemini first, standard/strong -> claude first.
    assert gw._provider_priority_order("research")[0] == "perplexity"
    assert gw._provider_priority_order("cheap")[0] == "gemini"
    assert gw._provider_priority_order("standard")[0] == "claude"
    assert gw._provider_priority_order("strong")[0] == "claude"


def test_lpr_osint_is_standard(all_keys, monkeypatch):
    # deep_lpr_osint analyses an already-gathered corpus -> standard (Sonnet), not research.
    seen = _record(monkeypatch)
    gw.complete_prompt_json_object("p", task_kind="lpr_osint")
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL


def test_cheap_falls_back_to_haiku_without_gemini_key(monkeypatch):
    # Every provider except gemini has a key; cheap tier prefers gemini but must fall to claude-haiku.
    monkeypatch.setattr(
        gw.settings, "LLM_PROVIDER_PRIORITY", "claude,gemini,openai,perplexity,grok"
    )
    monkeypatch.setattr(gw, "_api_key_for", lambda name: "" if name == "gemini" else f"k-{name}")
    seen = _record(monkeypatch)
    gw.complete_prompt_json_object("p", task_kind="program_match")
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL_CHEAP


def test_invalid_json_from_first_provider_falls_through(all_keys, monkeypatch):
    # cheap tier: gemini is first but returns non-JSON -> counts as failure -> claude (haiku) wins.
    seen = _record(monkeypatch, gemini_returns="sorry, not json here")
    out = gw.complete_prompt_json_object("p", task_kind="program_match")
    assert out == {"ok": True}
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL_CHEAP


def test_followup_draft_does_not_raise(all_keys, monkeypatch):
    # Regression: followup prompt matches no content marker; task_kind="followup_draft" must route live.
    seen = _record(monkeypatch)
    out = gw.generate_json("write a short follow-up email", task_kind="followup_draft")
    assert out == {"ok": True}
    assert seen["provider"] == "claude"
    assert seen["model"] == gw.settings.ANTHROPIC_MODEL  # standard tier


def test_followup_draft_raises_without_keys(monkeypatch):
    monkeypatch.setattr(gw, "_api_key_for", lambda name: "")
    with pytest.raises(ValueError):
        gw.generate_json("write a short follow-up email", task_kind="followup_draft")


# --- _gemini_complete: HTTP response parsing (no network — httpx.Client is replaced entirely) ---


class _FakeHttpxResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class _FakeHttpxClient:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        return self._response


def _patch_httpx_client(monkeypatch, response):
    monkeypatch.setattr(gw.httpx, "Client", lambda **kwargs: _FakeHttpxClient(response))


def test_gemini_complete_happy_path(monkeypatch):
    resp = _FakeHttpxResponse(
        200, {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
    )
    _patch_httpx_client(monkeypatch, resp)
    out = gw._gemini_complete("prompt", "key", "gemini-flash-latest", json_mode=True)
    assert out == '{"ok": true}'


def test_gemini_complete_no_candidates_raises(monkeypatch):
    resp = _FakeHttpxResponse(200, {"candidates": []})
    _patch_httpx_client(monkeypatch, resp)
    with pytest.raises(ValueError, match="no candidates"):
        gw._gemini_complete("prompt", "key", "model", json_mode=True)


def test_gemini_complete_blocked_response_raises(monkeypatch):
    # e.g. finishReason=SAFETY: candidates present but content/parts missing entirely.
    resp = _FakeHttpxResponse(200, {"candidates": [{"finishReason": "SAFETY"}]})
    _patch_httpx_client(monkeypatch, resp)
    with pytest.raises(ValueError, match="no text"):
        gw._gemini_complete("prompt", "key", "model", json_mode=True)


def test_gemini_complete_http_error_raises(monkeypatch):
    resp = _FakeHttpxResponse(404, {}, text="model not found")
    _patch_httpx_client(monkeypatch, resp)
    with pytest.raises(ValueError, match="Gemini HTTP 404"):
        gw._gemini_complete("prompt", "key", "bad-model", json_mode=True)


# --- kimi (Ollama Cloud, Anthropic-compatible endpoint) — B-372 --------------------------------


class _FakeHttpxClientCaptured:
    def __init__(self, response, captured: dict):
        self._response = response
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, *, headers, json):
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["payload"] = json
        return self._response


def _patch_httpx_client_captured(monkeypatch, response):
    captured: dict = {}
    monkeypatch.setattr(gw.httpx, "Client", lambda **kwargs: _FakeHttpxClientCaptured(response, captured))
    return captured


def test_kimi_complete_routes_to_ollama_url_with_bearer_no_x_api_key(monkeypatch):
    monkeypatch.setattr(gw.settings, "OLLAMA_ANTHROPIC_BASE_URL", "https://ollama.com")
    resp = _FakeHttpxResponse(200, {"content": [{"type": "text", "text": '{"ok": true}'}], "usage": {}})
    captured = _patch_httpx_client_captured(monkeypatch, resp)
    out = gw._kimi_complete("hello prompt", "kimi-token", "kimi-k2.7-code")
    assert out == '{"ok": true}'
    assert captured["url"] == "https://ollama.com/v1/messages"
    assert captured["headers"]["Authorization"] == "Bearer kimi-token"
    assert "x-api-key" not in captured["headers"]
    assert captured["payload"]["model"] == "kimi-k2.7-code"
    assert captured["payload"]["messages"][0]["content"] == "hello prompt"


def test_kimi_complete_strips_trailing_slash_from_base_url(monkeypatch):
    monkeypatch.setattr(gw.settings, "OLLAMA_ANTHROPIC_BASE_URL", "https://ollama.com/")
    resp = _FakeHttpxResponse(200, {"content": [{"type": "text", "text": '{"ok": true}'}], "usage": {}})
    captured = _patch_httpx_client_captured(monkeypatch, resp)
    gw._kimi_complete("p", "token", "kimi-k2.7-code")
    assert captured["url"] == "https://ollama.com/v1/messages"


def test_kimi_complete_cache_prefix_is_concatenated_not_cache_control(monkeypatch):
    # B-372: Ollama Cloud may not support cache_control — an unknown marker could break the
    # request, so kimi always glues cache_prefix onto prompt as a plain string, even when the
    # prefix is long enough that Claude would use the two-block cache_control form.
    monkeypatch.setattr(gw.settings, "OLLAMA_ANTHROPIC_BASE_URL", "https://ollama.com")
    resp = _FakeHttpxResponse(200, {"content": [{"type": "text", "text": '{"ok": true}'}], "usage": {}})
    captured = _patch_httpx_client_captured(monkeypatch, resp)
    long_prefix = "X" * 5000  # over _MIN_CACHE_PREFIX_CHARS
    gw._kimi_complete("rest of prompt", "token", "kimi-k2.7-code", cache_prefix=long_prefix)
    content = captured["payload"]["messages"][0]["content"]
    assert content == long_prefix + "rest of prompt"
    assert isinstance(content, str)  # not the two-block cache_control list


def test_kimi_complete_http_error_raises(monkeypatch):
    monkeypatch.setattr(gw.settings, "OLLAMA_ANTHROPIC_BASE_URL", "https://ollama.com")
    resp = _FakeHttpxResponse(401, {}, text="unauthorized")
    _patch_httpx_client_captured(monkeypatch, resp)
    with pytest.raises(ValueError, match="Kimi HTTP 401"):
        gw._kimi_complete("p", "bad-token", "kimi-k2.7-code")


def test_model_for_kimi_uses_kimi_model_setting(monkeypatch):
    monkeypatch.setattr(gw.settings, "KIMI_MODEL", "kimi-k2.7-code")
    assert gw._model_for("kimi", "cheap") == "kimi-k2.7-code"


def test_kimi_arm_routes_when_key_present(all_keys, monkeypatch):
    # kimi is appended to LLM_KEY_BY_PROVIDER order (after grok) — with no explicit
    # LLM_PROVIDER_PRIORITY / _TIER_PREFERRED_PROVIDER change, claude still wins tier "standard".
    # Restrict priority to kimi only to exercise the dispatch branch in _complete_with_fallback.
    monkeypatch.setattr(gw, "_api_key_for", lambda name: "k-kimi" if name == "kimi" else "")
    monkeypatch.setattr(gw.settings, "LLM_PROVIDER_PRIORITY", "kimi")
    seen: dict = {}

    def fake_kimi(prompt, api_key, model, cache_prefix=None):
        seen.update(provider="kimi", model=model, prompt=prompt)
        return '{"ok": true}'

    monkeypatch.setattr(gw, "_kimi_complete", fake_kimi)
    out = gw.complete_prompt_json_object("p", task_kind="program_match")
    assert out == {"ok": True}
    assert seen["provider"] == "kimi"
    assert seen["model"] == gw.settings.KIMI_MODEL


def test_kimi_provider_skipped_without_token(monkeypatch):
    # No OLLAMA_ANTHROPIC_TOKEN configured -> kimi is just skipped, like any other unkeyed provider.
    monkeypatch.setattr(gw, "_api_key_for", lambda name: "" if name == "kimi" else f"k-{name}")
    monkeypatch.setattr(gw.settings, "LLM_PROVIDER_PRIORITY", "kimi,claude")
    seen = _record(monkeypatch)
    out = gw.complete_prompt_json_object("p")
    assert out == {"ok": True}
    assert seen["provider"] == "claude"
