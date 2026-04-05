"""
E2E: generate_emails uses per-run master draft + placeholders (not DB templates).
DB template edits must not change generated outreach when master draft exists.
Run from host with API up: python scripts/verify_template_emails.py
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.services.outreach_personalize import (  # noqa: E402
    personalize_outbound,
    select_variant_for_contact,
)

BASE = "http://127.0.0.1:8000"


def req(method: str, path: str, body: dict | None = None) -> dict | list:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def approve_valid_contacts_for_run(run_id: int) -> None:
    contacts = req("GET", f"/contacts/run/{run_id}")  # type: ignore
    for c in contacts:
        if c["status"] == "valid" and c.get("review_status") == "pending":
            req(
                "PATCH",
                f"/contacts/{c['id']}/review",
                {"review_status": "approved"},
            )
    run_after = req("POST", f"/runs/{run_id}/continue", None)  # type: ignore
    assert run_after["status"] == "drafts_ready", run_after


def docker_seed_templates():
    subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "PYTHONPATH=/app",
            "ai_biz_backend",
            "python",
            "-m",
            "app.seed_templates",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def psql_update_subject(new_content: str, template_type: str = "outreach_subject"):
    esc = new_content.replace("'", "''")
    sql = (
        f"UPDATE templates SET content = '{esc}' "
        f"WHERE template_type = '{template_type}' AND project_id IS NULL;"
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "ai_biz_postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "ai_biz_os",
            "-c",
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main():
    try:
        req("GET", "/health")
    except urllib.error.URLError as e:
        print("API not reachable at", BASE, e, file=sys.stderr)
        sys.exit(1)

    print("=== Seed templates (docker) ===")
    try:
        docker_seed_templates()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print("docker seed skipped:", e)

    print("=== Load templates from API ===")
    templates = req("GET", "/templates")  # type: ignore
    by_type = {t["template_type"]: t for t in templates}
    assert "outreach_subject" in by_type and "outreach_body" in by_type, by_type.keys()
    subj_tmpl = by_type["outreach_subject"]["content"]
    _ = by_type["outreach_body"]["content"]

    print("DB subject template:", repr(subj_tmpl[:70]))

    print("=== Run workflow #1 ===")
    project = req("POST", "/projects", {"name": "tpl verify 1", "type": "outreach"})  # type: ignore
    pid = project["project_id"]
    outreach_brief = (
        "Offer: Test offer\n"
        "Target: Test companies\n"
        "Roles: Test roles\n"
        "Goal: Verify master email path\n"
        "Tone: Professional\n"
        "Notes:\n"
    )
    brief = {
        "project_id": pid,
        "workflow_name": "generic_outreach",
        "input_json": {},
        "name": "tpl verify run",
        "segment": "test",
        "outreach_brief": outreach_brief,
    }
    run = req("POST", "/runs/start", brief)  # type: ignore
    rid = run["id"]
    assert run["status"] == "needs_review", run
    approve_valid_contacts_for_run(rid)
    run_done = req("GET", f"/runs/{rid}")  # type: ignore
    steps = req("GET", f"/steps/run/{rid}")  # type: ignore
    ge = next(s for s in steps if s["step_name"] == "generate_emails")
    emails = ge["output_json"]["emails"]
    assert emails, "no emails"

    cl = req("GET", f"/contacts/run/{rid}")  # type: ignore
    assert isinstance(cl, list) and cl, "no contacts from DB"
    contact = cl[0]
    me = run_done.get("master_email") or {}
    variants = me.get("variants") if isinstance(me, dict) else None
    assert isinstance(variants, list) and len(variants) == 3, me
    contact_ns = SimpleNamespace(
        id=int(emails[0]["contact_id"]),
        company=contact.get("company") or "",
        website=contact.get("website") or "",
        name=contact.get("name") or "",
        role=contact.get("role") or "",
        email=contact.get("email") or "",
    )
    variant, _variant_idx = select_variant_for_contact(rid, contact_ns.id, variants)
    exp_subj, exp_body = personalize_outbound(
        rid,
        contact_ns,
        variant["subject"],
        variant["body"],
    )
    assert emails[0]["subject"] == exp_subj, (emails[0]["subject"], exp_subj)
    assert emails[0]["body"] == exp_body, (emails[0]["body"][:200], exp_body[:200])
    print("OK run1: email subject/body match chosen variant + personalization.")

    print("=== Change subject template in Postgres ===")
    new_subj = "DB_OVERRIDDEN_SUBJECT for {{company}} — v2"
    psql_update_subject(new_subj)

    templates2 = req("GET", "/templates")  # type: ignore
    by_type2 = {t["template_type"]: t for t in templates2}
    assert by_type2["outreach_subject"]["content"] == new_subj
    print("API sees updated subject template.")

    print("=== Run workflow #2 (new run) ===")
    project2 = req("POST", "/projects", {"name": "tpl verify 2", "type": "outreach"})  # type: ignore
    pid2 = project2["project_id"]
    run2 = req("POST", "/runs/start", {**brief, "project_id": pid2, "name": "tpl verify run 2"})  # type: ignore
    rid2 = run2["id"]
    assert run2["status"] == "needs_review", run2
    approve_valid_contacts_for_run(rid2)
    run_done2 = req("GET", f"/runs/{rid2}")  # type: ignore
    steps2 = req("GET", f"/steps/run/{rid2}")  # type: ignore
    ge2 = next(s for s in steps2 if s["step_name"] == "generate_emails")
    emails2 = ge2["output_json"]["emails"]
    cl2 = req("GET", f"/contacts/run/{rid2}")  # type: ignore
    assert isinstance(cl2, list) and cl2, "no contacts from DB (run2)"
    c2 = cl2[0]
    me2 = run_done2.get("master_email") or {}
    variants2 = me2.get("variants") if isinstance(me2, dict) else None
    assert isinstance(variants2, list) and len(variants2) == 3, me2
    c2_ns = SimpleNamespace(
        id=int(emails2[0]["contact_id"]),
        company=c2.get("company") or "",
        website=c2.get("website") or "",
        name=c2.get("name") or "",
        role=c2.get("role") or "",
        email=c2.get("email") or "",
    )
    v2, _v2_idx = select_variant_for_contact(rid2, c2_ns.id, variants2)
    exp2_subj, _exp2_body = personalize_outbound(rid2, c2_ns, v2["subject"], v2["body"])
    assert emails2[0]["subject"] == exp2_subj
    print(
        "OK run2: subject matches variant path; DB template override does not affect master variants:",
        repr(emails2[0]["subject"]),
    )

    # restore template for local dev hygiene
    psql_update_subject(subj_tmpl)
    print("Restored original subject template in DB.")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
