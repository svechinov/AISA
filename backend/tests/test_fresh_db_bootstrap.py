"""Fresh-DB bootstrap (fork-transition Phase 1, Task 2): ensure_schema()/create_all() must
register every application table on a CLEAN database, not just upgrade an existing snapshot in
place. AUDIT_2026-06-16.md flagged this as a latent bootstrap bug: system_setting/smtp_account
only get registered onto Base.metadata when their service modules happen to be imported, with no
guaranteed ordering between the schema task and the routes task. Masked in prod by an existing
snapshot; this test is the fresh-checkout case that would catch it. 0 tokens: no LLM/network."""

from sqlalchemy import inspect


def test_fresh_db_has_all_core_tables(fresh_db):
    tables = set(inspect(fresh_db.get_bind()).get_table_names())

    expected = {
        "projects",
        "runs",
        "run_setups",
        "contacts",
        "email_drafts",
        "system_settings",
        "smtp_accounts",
        "sending_policies",
        "send_queue",
        "suppression_list",
        "personas",
        "excluded_companies",
        "company_evidence",
        "training_programs",
        "draft_instruct_log",
    }
    missing = expected - tables
    assert not missing, f"tables missing from a fresh bootstrap: {sorted(missing)}"
