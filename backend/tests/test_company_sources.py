"""Phase 4: company source extractor + append helper (stubbed Tavily/LLM, 0 tokens)."""

import pytest

import app.services.company_source_extractor as cse
from app.models.run_company import RunCompany
from app.repositories.run_company_repo import append_companies_to_run
from app.utils.run_company_extra import effective_run_company_extra

RUN_ID = 999_004  # throwaway namespace


@pytest.fixture()
def cleanup(db):
    yield
    db.query(RunCompany).filter_by(run_id=RUN_ID).delete(synchronize_session=False)
    db.commit()


class _FakeTavily:
    def __init__(self, extract_text="", search_results=None):
        self.extract_text = extract_text
        self.search_results = search_results or []

    def extract(self, urls):
        return {"results": [{"url": urls[0], "raw_content": self.extract_text}]}

    def search(self, **kw):
        return {"results": self.search_results}


def test_extract_url_parses_companies(db, cleanup, monkeypatch):
    monkeypatch.setattr(cse, "get_tavily_client",
                        lambda: _FakeTavily(extract_text="1. Альфа 2. Бета"))
    monkeypatch.setattr(cse, "complete_prompt_json_object", lambda p: {"companies": [
        {"name": "Альфа", "website": "alfa.test", "note": "топ-1"},
        {"name": "Бета", "website": "", "note": ""},
        {"name": "", "website": "skip.test"},  # no name -> dropped
    ]})
    companies = cse.extract_companies_from_url("https://rating.test/top")
    assert [c["name"] for c in companies] == ["Альфа", "Бета"]


def test_extract_url_rejects_bad_url(db):
    with pytest.raises(ValueError):
        cse.extract_companies_from_url("rating.test/top")


def test_tenders_extract_buyers(db, cleanup, monkeypatch):
    import app.services.search_service as ss
    monkeypatch.setattr(ss, "search_web", lambda q, **k: [
        {"title": "Закупка", "url": "https://zakupki.gov.ru/x", "snippet": "Заказчик: ПАО Гамма, тренинг продаж"},
    ])
    monkeypatch.setattr(cse, "complete_prompt_json_object", lambda p: {"companies": [
        {"name": "ПАО Гамма", "website": "", "note": "закупает тренинг продаж"},
    ]})
    data = cse.extract_companies_from_tenders("тренинг продаж")
    assert data["companies"][0]["name"] == "ПАО Гамма"
    assert data["urls"] == ["https://zakupki.gov.ru/x"]


def test_append_dedupes_and_records_source(db, cleanup):
    out1 = append_companies_to_run(db, RUN_ID, [
        {"name": "Альфа", "website": "alfa.test", "note": "топ-1"},
        {"name": "Бета", "website": ""},
    ], source={"type": "rating_url", "url": "https://r.test"})
    assert out1["added"] == ["Альфа", "Бета"] and out1["skipped_duplicates"] == 0

    # same name OR same website → duplicate; new company appended with continued index
    out2 = append_companies_to_run(db, RUN_ID, [
        {"name": "АЛЬФА", "website": ""},             # name match (case-insensitive)
        {"name": "Alfa Group", "website": "alfa.test"},  # website match
        {"name": "Гамма", "website": "gamma.test"},
    ], source={"type": "tender_intent", "query": "q"})
    assert out2["added"] == ["Гамма"] and out2["skipped_duplicates"] == 2

    rows = (db.query(RunCompany).filter_by(run_id=RUN_ID)
            .order_by(RunCompany.collect_index.asc()).all())
    assert [r.collect_index for r in rows] == [1, 2, 3]

    kv = effective_run_company_extra(db, rows[0])
    assert kv["company_source"]["type"] == "rating_url"
    assert kv["company_source"]["note"] == "топ-1"
    kv3 = effective_run_company_extra(db, rows[2])
    assert kv3["company_source"]["type"] == "tender_intent"


def test_appended_companies_visible_to_fit_judge(db, cleanup):
    """Appended rows are plain run_companies rows: ai_fit_checked_at is NULL → analyze-fit
    picks them up, and the ICP gate honors a later 'incorrect' verdict (existing tests)."""
    append_companies_to_run(db, RUN_ID, [{"name": "Дельта", "website": "delta.test"}],
                            source={"type": "criterion", "criterion": "c"})
    row = db.query(RunCompany).filter_by(run_id=RUN_ID, name="Дельта").one()
    assert row.ai_fit_checked_at is None and row.ai_fit_status is None
