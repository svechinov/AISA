"""B-445: gather_raw_entities must not let the LLM invent a source_url — only a URL that is
verbatim present in the search corpus we actually handed it (roles/email/docs) may survive."""

import json

import app.services.hardcore_osint as ho


def _stub_common(monkeypatch, corpus: str):
    monkeypatch.setattr(ho, "search_egrul_nalog", lambda q: None)
    monkeypatch.setattr(ho, "search_ddg", lambda q, max_res=5: corpus)


def test_source_url_kept_when_present_in_corpus(monkeypatch):
    corpus = "Иван Иванов, коммерческий директор — https://hh.ru/resume/123 (2025)"
    _stub_common(monkeypatch, corpus)
    monkeypatch.setattr(
        ho, "call_llm_json",
        lambda prompt, task_kind="osint_entity_extract": json.dumps({
            "leaders": [
                {"role": "CEO", "name": "Иван Иванов", "freshness_score": 90,
                 "source_url": "https://hh.ru/resume/123"},
            ],
            "email_mask_guess": None,
        }),
    )
    out = ho.gather_raw_entities("Test Co", "test.co")
    assert out["leaders"][0]["source_url"] == "https://hh.ru/resume/123"


def test_source_url_dropped_when_not_in_corpus(monkeypatch):
    corpus = "Иван Иванов, коммерческий директор, без ссылок в выдаче (2025)"
    _stub_common(monkeypatch, corpus)
    monkeypatch.setattr(
        ho, "call_llm_json",
        lambda prompt, task_kind="osint_entity_extract": json.dumps({
            "leaders": [
                {"role": "CEO", "name": "Иван Иванов", "freshness_score": 90,
                 "source_url": "https://invented.example/not-in-corpus"},
            ],
            "email_mask_guess": None,
        }),
    )
    out = ho.gather_raw_entities("Test Co", "test.co")
    assert out["leaders"][0]["source_url"] is None
