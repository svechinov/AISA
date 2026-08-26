#!/usr/bin/env python3
"""Read-only regression re-runner: re-run the taste rubric on already-verdicted drafts against
the CURRENT canon of judgement, holding the evidence input frozen (B-077 etap 2 — see
docs/critic-canon.md and docs/b077-critic-calibration-handoff-2026-07-16.md, "Дельта приёмки этапа
2" #2).

Why a frozen input matters: without it, re-running the critic on a draft conflates two variables —
did the verdict change because the canon changed, or because the evidence changed since generation?
`critic_evidence_json` (the same company/person/vacancy evidence the ORIGINAL judgement saw) and
`critic_canon_used` (the canon text that was active then) are persisted per-draft precisely so this
script can hold evidence fixed and vary only the canon.

For each draft in a run with a non-empty ``alex_verdict`` AND a taste verdict already on file
(``critic_evidence_json`` and ``critic_taste_pass`` both set — see critic_vs_alex_report.py for why
mechanically-cut drafts don't have one), re-runs ``_run_taste_rubric`` with the FROZEN evidence but
the run's CURRENT canon (``get_critic_canon_text(run) or DEFAULT_CRITIC_CANON``) and compares the
new taste-vs-Alex bucket against the one already on file.

Success criterion: "the number of disagreements (critic_blind + critic_nitpicks +
borderline_reject_edits) went down" — NOT "everything now matches". The LLM is non-deterministic;
demanding unanimous agreement would just be measuring noise. "Sensitive" drafts — ones whose OLD
bucket was borderline_reject_edits, OR whose NEW total lands within ±2 of CRITIC_MIN_TOTAL — are run
TWICE; if the two runs disagree on taste_pass, the draft is flagged UNSTABLE (noise, not signal).

A canon edit is not considered accepted until this script shows fewer disagreements than before
(see docs/critic-canon.md "Как пополнять канон") — a canon line is a hypothesis, and the critic has
already ignored direct instructions once (the Horns Up case).

READ-ONLY BY DESIGN — no writes, ever. This only calls the LLM critic and prints a comparison.

RUNNING ON THE SERVER — same situation as critic_vs_alex_report.py (see that file's docstring for
why): not present inside the running container image, run it the same way as a one-off script
against the prod DB:

    scp backend/scripts/critic_regression_rerun.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/critic_regression_rerun.py [run_id]'
    ssh bizos 'rm ~/ai-biz-os/infra/data/critic_regression_rerun.py'  # data/ is the live
                                                                       # bind-mounted volume —
                                                                       # don't leave stray files
                                                                       # in it between uses.

The script itself stays committed in backend/scripts/; only the on-server copy is transient.

Loads /app/data/.env into os.environ BEFORE importing app.config/app.db, because DATABASE_URL (and
the LLM keys) must already be in os.environ when Settings() is instantiated — the container has no
/app/.env of its own; the real config lives in the bind-mounted data/.env. Locally (dev), run from
backend/ with the venv active and your usual .env in place — the /app/data/.env load below is a
no-op if that path does not exist.

Usage:
    python3 critic_regression_rerun.py [run_id]     # default: the most recent run
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from pathlib import Path

# --- Load /app/data/.env into the process environment BEFORE importing app.config/app.db ---
_DATA_ENV = Path("/app/data/.env")
if _DATA_ENV.is_file():
    for _line in _DATA_ENV.read_text(encoding="utf-8").splitlines():
        s = _line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        _key, _, _val = s.partition("=")
        _key = _key.strip()
        _val = _val.strip()
        if len(_val) >= 2 and _val[0] == _val[-1] and _val[0] in "\"'":
            _val = _val[1:-1]
        if _key:
            os.environ[_key] = _val

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import app.models  # noqa: E402 — package with __path__, for the pkgutil walk below

# Import every model module so SQLAlchemy's mapper configuration sees all relationships —
# skipping one here risks "expression 'X' failed to locate a name" the first time a relationship
# is touched.
for _mod in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_mod.name}")

from app.constants.alex_verdict import ALEX_VERDICTS  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.email_draft import EmailDraft  # noqa: E402
from app.models.run import Run  # noqa: E402
from app.services.critic_canon import DEFAULT_CRITIC_CANON  # noqa: E402
from app.services.email_validation_service import CRITIC_MIN_TOTAL, _run_taste_rubric  # noqa: E402
from app.services.run_context_service import get_critic_canon_text  # noqa: E402

# Old bucket == borderline, or new total within this many points of the pass/fail line — re-run
# twice, since a judgement that close to the threshold is the most likely to flip on noise alone.
_SENSITIVE_TOTAL_MARGIN = 2

DISAGREEMENT_BUCKETS = ("critic_blind", "critic_nitpicks", "borderline_reject_edits")


def _resolve_run_id(db, arg: str | None) -> int | None:
    if arg:
        return int(arg)
    last = db.query(Run).order_by(Run.id.desc()).first()
    return last.id if last else None


def _bucket(taste_pass: bool | None, verdict: str | None) -> str | None:
    """Same taste<->Alex matrix as critic_vs_alex_report.py, for a single (taste_pass, verdict) pair."""
    if verdict not in ALEX_VERDICTS or taste_pass is None:
        return None
    if taste_pass:
        return "critic_blind" if verdict == "would_not_send" else "agreement_pass"
    if verdict == "ok_as_is":
        return "critic_nitpicks"
    if verdict == "would_not_send":
        return "agreement_reject"
    return "borderline_reject_edits"  # ok_with_edits


def _rerun(subject: str, body: str, evidence: dict, canon: str) -> dict | None:
    return _run_taste_rubric(
        subject, body,
        evidence.get("company_ev"), evidence.get("person_ev"), evidence.get("vacancy_ev"),
        canon,
    )


def run_regression(db, run_id: int) -> list[dict]:
    """Read-only: re-judge every taste-evaluated, verdicted draft in run_id against the CURRENT
    canon with FROZEN evidence. Returns a list of per-draft result dicts."""
    run = db.get(Run, run_id)
    current_canon = get_critic_canon_text(run) or DEFAULT_CRITIC_CANON

    drafts = (
        db.query(EmailDraft)
        .filter(
            EmailDraft.run_id == run_id,
            EmailDraft.alex_verdict.isnot(None),
            EmailDraft.critic_evidence_json.isnot(None),
            EmailDraft.critic_taste_pass.isnot(None),
        )
        .order_by(EmailDraft.id.asc())
        .all()
    )

    results: list[dict] = []
    for d in drafts:
        evidence = d.critic_evidence_json or {}
        old_bucket = _bucket(d.critic_taste_pass, d.alex_verdict)

        first = _rerun(d.subject, d.body, evidence, current_canon)
        if first is None:
            # LLM not configured in this environment — nothing to compare.
            results.append({"draft": d, "skipped": "LLM not configured"})
            continue

        new_taste_pass = first["taste_pass"]
        sensitive = old_bucket == "borderline_reject_edits" or (
            abs(first["total"] - CRITIC_MIN_TOTAL) <= _SENSITIVE_TOTAL_MARGIN
        )
        unstable = False
        if sensitive:
            second = _rerun(d.subject, d.body, evidence, current_canon)
            if second is not None and second["taste_pass"] != new_taste_pass:
                unstable = True

        results.append({
            "draft": d,
            "old_taste_pass": d.critic_taste_pass,
            "new_taste_pass": new_taste_pass,
            "old_bucket": old_bucket,
            "new_bucket": _bucket(new_taste_pass, d.alex_verdict),
            "unstable": unstable,
        })
    return results


def print_regression(run_id: int, results: list[dict]) -> None:
    evaluated = [r for r in results if "skipped" not in r]
    skipped = [r for r in results if "skipped" in r]

    print(f"=== critic regression rerun — run_id={run_id} ({len(evaluated)} drafts re-judged) ===\n")

    old_disagreements = sum(1 for r in evaluated if r["old_bucket"] in DISAGREEMENT_BUCKETS)
    new_disagreements = sum(1 for r in evaluated if r["new_bucket"] in DISAGREEMENT_BUCKETS)
    print(f"Disagreements (old canon): {old_disagreements}/{len(evaluated)}")
    print(f"Disagreements (current canon, frozen evidence): {new_disagreements}/{len(evaluated)}")

    if new_disagreements < old_disagreements:
        print("Verdict: IMPROVED — disagreements went down.")
    elif new_disagreements > old_disagreements:
        print("Verdict: WORSENED — disagreements went up.")
    else:
        print("Verdict: NO CHANGE in disagreement count.")
    print(
        "(Success criterion is fewer disagreements, not unanimous agreement — the LLM is "
        "non-deterministic.)",
    )

    print("\nPer-draft:")
    for r in evaluated:
        d = r["draft"]
        flag = " UNSTABLE" if r["unstable"] else ""
        print(
            f"    draft_id={d.id} company={d.company!r} alex_verdict={d.alex_verdict!r} "
            f"old_taste_pass={r['old_taste_pass']} -> new_taste_pass={r['new_taste_pass']}{flag}",
        )
    for r in skipped:
        d = r["draft"]
        print(f"    draft_id={d.id} company={d.company!r} SKIPPED ({r['skipped']})")


def main() -> int:
    run_id_arg = sys.argv[1] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        run_id = _resolve_run_id(db, run_id_arg)
        if run_id is None:
            print("No runs found in this database.", file=sys.stderr)
            return 1
        results = run_regression(db, run_id)
        print_regression(run_id, results)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
