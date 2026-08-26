"""B-371: Anthropic prompt caching on stable prompt prefixes (prompt_setup_text).

Fully offline — httpx.Client is replaced entirely, no network calls. Covers:
- _anthropic_complete payload shape (string content vs. two-block content with cache_control)
- the 4000-char threshold below which caching is a no-op and prompts are concatenated
- non-Anthropic providers always get the concatenated string (fallback behavior unchanged)
- build_prompt_split's invariant: prefix + rest == build_prompt(task=cacheable_prefix + task, ...)
"""

import app.services.llm_gateway as gw
from app.services.prompt_builder import build_prompt, build_prompt_split


class _FakeHttpxResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class _FakeHttpxClient:
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


def _patch_httpx_client(monkeypatch, response):
    captured: dict = {}
    monkeypatch.setattr(gw.httpx, "Client", lambda **kwargs: _FakeHttpxClient(response, captured))
    return captured


def _anthropic_ok_response(usage=None):
    return _FakeHttpxResponse(
        200,
        {
            "content": [{"type": "text", "text": '{"ok": true}'}],
            "usage": usage or {},
        },
    )


def test_anthropic_complete_no_cache_prefix_uses_string_content(monkeypatch):
    captured = _patch_httpx_client(monkeypatch, _anthropic_ok_response())
    out = gw._anthropic_complete("hello prompt", "key", "claude-sonnet-5")
    assert out == '{"ok": true}'
    content = captured["payload"]["messages"][0]["content"]
    assert content == "hello prompt"


def test_anthropic_complete_long_cache_prefix_uses_two_blocks(monkeypatch):
    captured = _patch_httpx_client(monkeypatch, _anthropic_ok_response())
    prefix = "X" * 5000  # over _MIN_CACHE_PREFIX_CHARS
    out = gw._anthropic_complete("rest of prompt", "key", "claude-sonnet-5", cache_prefix=prefix)
    assert out == '{"ok": true}'
    content = captured["payload"]["messages"][0]["content"]
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[0]["text"] == prefix
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in content[1]
    assert content[1]["text"] == "rest of prompt"


def test_anthropic_complete_short_cache_prefix_concatenates(monkeypatch):
    captured = _patch_httpx_client(monkeypatch, _anthropic_ok_response())
    prefix = "X" * 100  # under _MIN_CACHE_PREFIX_CHARS
    out = gw._anthropic_complete("rest of prompt", "key", "claude-sonnet-5", cache_prefix=prefix)
    assert out == '{"ok": true}'
    content = captured["payload"]["messages"][0]["content"]
    assert content == prefix + "rest of prompt"


def test_anthropic_complete_logs_cache_usage(monkeypatch, caplog):
    _patch_httpx_client(
        monkeypatch,
        _anthropic_ok_response(usage={"cache_creation_input_tokens": 4300, "cache_read_input_tokens": 0, "input_tokens": 4310}),
    )
    with caplog.at_level("INFO"):
        gw._anthropic_complete("rest of prompt", "key", "claude-sonnet-5", cache_prefix="X" * 5000)
    assert any(
        "Anthropic cache" in r.message and "write=4300" in r.message and "read=0" in r.message
        for r in caplog.records
    )


def test_non_anthropic_provider_gets_concatenated_prompt(monkeypatch):
    # gemini/openai/perplexity/grok have no cache mechanism here — cache_prefix must be glued back
    # onto the prompt so their behavior is exactly what it was before B-371.
    monkeypatch.setattr(gw, "_api_key_for", lambda name: "k-gemini" if name == "gemini" else "")
    monkeypatch.setattr(gw.settings, "LLM_PROVIDER_PRIORITY", "gemini")

    seen: dict = {}

    def fake_gemini(prompt, api_key, model, *, json_mode):
        seen["prompt"] = prompt
        return '{"ok": true}'

    monkeypatch.setattr(gw, "_gemini_complete", fake_gemini)

    out = gw._complete_with_fallback("rest", "standard", cache_prefix="PREFIX-")
    assert out == {"ok": True}
    assert seen["prompt"] == "PREFIX-rest"


def test_build_prompt_split_invariant_with_prefix():
    task = "do the thing"
    data = {"a": 1, "b": [1, 2, 3]}
    rules = ["rule one", "rule two"]
    schema = {"type": "object"}
    cacheable_prefix = "Campaign / prompt setup (primary):\nHARD RULES here\n\n"

    prefix, rest = build_prompt_split(
        task=task, data=data, rules=rules, output_schema=schema, cacheable_prefix=cacheable_prefix
    )
    expected = build_prompt(task=cacheable_prefix + task, data=data, rules=rules, output_schema=schema)
    assert prefix + rest == expected
    assert prefix.endswith(cacheable_prefix)


def test_build_prompt_split_no_prefix_returns_full_prompt_unchanged():
    task = "do the thing"
    data = {"a": 1}
    rules = ["rule one"]
    prefix, rest = build_prompt_split(task=task, data=data, rules=rules, cacheable_prefix=None)
    assert prefix == ""
    assert rest == build_prompt(task=task, data=data, rules=rules)

    prefix2, rest2 = build_prompt_split(task=task, data=data, rules=rules, cacheable_prefix="")
    assert prefix2 == ""
    assert rest2 == build_prompt(task=task, data=data, rules=rules)
