"""Web search provider (R4): priority fallback, Yandex XML parse, Agent B RU corpus."""

import base64

import pytest

import app.services.search_service as ss


def _yandex_xml(docs):
    items = "".join(
        f"<doc><url>{u}</url><title>{t}</title>"
        f"<passages><passage>{p}</passage></passages></doc>"
        for (u, t, p) in docs
    )
    return base64.b64encode(
        f"<yandexsearch><response><results><grouping><group>{items}"
        f"</group></grouping></results></response></yandexsearch>".encode("utf-8")
    ).decode()


def test_yandex_xml_parse():
    raw = _yandex_xml([("https://vk.com/x", "VK post", "Шаройкина Воркутауголь"),
                       ("https://t.me/y", "TG", "пресс-служба")])
    out = ss._parse_yandex_xml(raw)
    assert [h["url"] for h in out] == ["https://vk.com/x", "https://t.me/y"]
    assert out[0]["title"] == "VK post" and "Шаройкина" in out[0]["snippet"]


def test_priority_yandex_then_tavily(monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "_provider_priority", lambda: ["yandex", "tavily"])
    monkeypatch.setattr(ss, "_yandex_search",
                        lambda q, **k: calls.append("y") or [{"title": "y", "url": "u", "snippet": "s"}])
    monkeypatch.setattr(ss, "_tavily_search", lambda q, **k: calls.append("t") or [])
    out = ss.search_web("q")
    assert out and calls == ["y"]  # yandex answered -> tavily not called


def test_fallback_to_tavily_when_yandex_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(ss, "_provider_priority", lambda: ["yandex", "tavily"])
    monkeypatch.setattr(ss, "_yandex_search", lambda q, **k: calls.append("y") or [])
    monkeypatch.setattr(ss, "_tavily_search",
                        lambda q, **k: calls.append("t") or [{"title": "t", "url": "u2", "snippet": "s"}])
    out = ss.search_web("q")
    assert calls == ["y", "t"] and out[0]["url"] == "u2"


def test_empty_query_and_all_miss(monkeypatch):
    assert ss.search_web("") == []
    monkeypatch.setattr(ss, "_provider_priority", lambda: ["yandex", "tavily"])
    monkeypatch.setattr(ss, "_yandex_search", lambda q, **k: [])
    monkeypatch.setattr(ss, "_tavily_search", lambda q, **k: [])
    assert ss.search_web("q") == []


def test_resolve_company_domain_skips_aggregators(monkeypatch):
    monkeypatch.setattr(ss, "search_web", lambda q, **k: [
        {"title": "list-org", "url": "https://www.list-org.com/company/1", "snippet": ""},
        {"title": "RBC", "url": "https://rbc.ru/news/x", "snippet": ""},
        {"title": "Official", "url": "https://moonmebel.ru/about", "snippet": ""},
    ])
    assert ss.resolve_company_domain("Мебельная фабрика Moon") == "moonmebel.ru"


def test_resolve_company_domain_none_when_all_aggregators(monkeypatch):
    monkeypatch.setattr(ss, "search_web", lambda q, **k: [
        {"title": "x", "url": "https://vk.com/club1", "snippet": ""},
        {"title": "y", "url": "https://hh.ru/employer/1", "snippet": ""},
    ])
    assert ss.resolve_company_domain("X") is None
    assert ss.resolve_company_domain("") is None


def test_yandex_not_configured_returns_empty(monkeypatch):
    monkeypatch.setattr(ss, "yandex_search_configured", lambda: False)
    assert ss._yandex_search("q", max_results=5, max_passages=5) == []


def test_agent_b_corpus_tiers_and_dedups(monkeypatch):
    """Agent B builds an RU corpus via search_web, deduping URLs across the query ladder."""
    import app.services.deep_lpr_osint as db_osint

    seen_queries = []

    def fake_search(q, **k):
        seen_queries.append(q)
        # strict query returns one hit; a later query repeats it + adds one
        if "интервью" in q:
            return [{"title": "VK", "url": "https://vk.com/a", "snippet": "пресс-служба Воркутауголь"}]
        return [{"title": "VK", "url": "https://vk.com/a", "snippet": "dup"},
                {"title": "TG", "url": "https://t.me/b", "snippet": "канал"}]

    monkeypatch.setattr(db_osint, "search_web", fake_search, raising=False)
    # search_web is imported inside the function; patch the module attr it pulls from
    import app.services.search_service as ss_mod
    monkeypatch.setattr(ss_mod, "search_web", fake_search)

    corpus = db_osint._person_search_corpus(
        "Ольга Шаройкина", "Воркутауголь", "пресс-служба", language="Russian",
    )
    assert "vk.com/a" in corpus and "t.me/b" in corpus
    assert corpus.count("vk.com/a") == 1  # deduped across tiers
    assert seen_queries[0].startswith("Ольга Шаройкина Воркутауголь интервью")  # RU keywords, strict first


def test_agent_b_english_query_ladder():
    """Non-Russian campaigns get English keywords and global social domains in the ladder."""
    import app.services.deep_lpr_osint as db_osint

    queries = db_osint._person_queries("Jane Doe", "Nekki", "CEO", "English")
    assert queries[0].startswith("Jane Doe Nekki interview OR podcast")
    assert any("linkedin.com" in q for q in queries)
    assert not any("vk.com" in q for q in queries)
