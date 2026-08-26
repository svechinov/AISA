"""B-445: contact provenance (source kind + source_url) round-trips through the KV store.

persist_contact_source writes into entity_json_kv (scope contact_source); effective_contact_source_json
reads it back (absorbing the legacy column on first read). New keys like "source"/"source_url" must
survive the round trip untouched, same as any other payload key.
"""

from app.models.contact import Contact
from app.utils.contact_source_payload import effective_contact_source_json, persist_contact_source


def test_source_and_source_url_round_trip_via_kv_store(db):
    row = Contact(run_id=1, source_json={})
    db.add(row)
    db.commit()
    try:
        persist_contact_source(
            db,
            row,
            {"source": "osint", "source_url": "https://hh.ru/resume/123", "freshness_score": 90},
        )
        db.commit()
        sj = effective_contact_source_json(db, row)
        assert sj["source"] == "osint"
        assert sj["source_url"] == "https://hh.ru/resume/123"
        assert sj["freshness_score"] == 90
    finally:
        db.delete(row)
        db.commit()


def test_source_url_none_round_trips_as_none(db):
    row = Contact(run_id=1, source_json={})
    db.add(row)
    db.commit()
    try:
        persist_contact_source(db, row, {"source": "osint", "source_url": None})
        db.commit()
        sj = effective_contact_source_json(db, row)
        assert sj["source"] == "osint"
        assert sj["source_url"] is None
    finally:
        db.delete(row)
        db.commit()


def test_llm_generated_source_round_trips(db):
    """Decision 11.08: the ungrounded LLM-fallback path (contacts_worker.find_contacts without
    Apollo) tags contacts "llm_generated" so they can never be mistaken for a found/verified
    source downstream — must survive the KV round trip like any other source kind."""
    row = Contact(run_id=1, source_json={})
    db.add(row)
    db.commit()
    try:
        persist_contact_source(db, row, {"source": "llm_generated"})
        db.commit()
        sj = effective_contact_source_json(db, row)
        assert sj["source"] == "llm_generated"
    finally:
        db.delete(row)
        db.commit()
