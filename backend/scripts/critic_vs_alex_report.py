#!/usr/bin/env python3
"""Read-only report: critic verdict vs Alex's verdict, for calibrating the canon of judgement
(B-077 etap 2 — see docs/critic-canon.md and docs/b077-critic-calibration-handoff-2026-07-16.md).

For each draft in a run with a non-empty ``alex_verdict``, crosses the critic's TASTE verdict
(``critic_taste_pass``: the LLM rubric's own pass/fail, separate from mechanical rejects — decision
4, B-077) against Alex's verdict and buckets into a matrix:

  - taste PASS + alex ok_as_is / ok_with_edits -> agreement_pass (critic let it through, Alex is fine)
  - taste PASS + alex would_not_send           -> critic_blind (let through what Alex would not send)
  - taste FAIL + alex ok_as_is                 -> critic_nitpicks (rejected what Alex is fine with)
  - taste FAIL + alex would_not_send           -> agreement_reject (both against)
  - taste FAIL + alex ok_with_edits            -> borderline_reject_edits, flagged separately

Only drafts where the taste rubric actually ran (``critic_taste_pass is not None``) enter the
matrix. Drafts cut by mechanics before the rubric ran (banned list / invented role / dup / template
drift — ``critic_taste_pass is None`` and ``generation_is_valid is False``) sit OUTSIDE the matrix
in ``cut_by_mechanics``: the critic was enforcing the law, not judging taste, so they must not read
as "critic nitpicks" against Alex. Drafts with no taste verdict for another reason (no_vacancy /
LLM off) land in ``no_taste_verdict``. Agreement rate is computed over the matrix only.

Output: summary counts per bucket + a list of the disagreement drafts (draft_id/company/score) for
manual review. Read-only — no writes, ever.

This is a REUSABLE tool: it lives in backend/scripts/ and is kept in git, unlike one-off scripts
against the prod DB (those get deleted after use per AI-Biz-OS/CLAUDE.md "Грабли").

RUNNING ON THE SERVER — checked backend/Dockerfile before writing this:
`Dockerfile` only ``COPY``s ``app/`` into the image, and ``infra/docker-compose.server.yml`` only
bind-mounts ``./data:/app/data`` (not scripts/). So this script is NOT present at any path inside
the running container — it cannot be invoked as ``/app/scripts/...``. Run it the same way as a
one-off script against the prod DB:

    scp backend/scripts/critic_vs_alex_report.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/critic_vs_alex_report.py [run_id]'
    ssh bizos 'rm ~/ai-biz-os/infra/data/critic_vs_alex_report.py'  # data/ is the live bind-mounted
                                                                     # volume — don't leave stray
                                                                     # files in it between uses.

The script itself stays committed in backend/scripts/; only the on-server copy is transient.

Loads /app/data/.env into os.environ BEFORE importing app.config/app.db, because DATABASE_URL (and
the LLM keys) must already be in os.environ when Settings() is instantiated — the container has no
/app/.env of its own; the real config lives in the bind-mounted data/.env. Locally (dev), run from
backend/ with the venv active and your usual .env in place — the /app/data/.env load below is a
no-op if that path does not exist.

Usage:
    python3 critic_vs_alex_report.py [run_id]     # default: the most recent run
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


def _resolve_run_id(db, arg: str | None) -> int | None:
    if arg:
        return int(arg)
    last = db.query(Run).order_by(Run.id.desc()).first()
    return last.id if last else None


MATRIX_KEYS = (
    "agreement_pass",
    "critic_blind",
    "critic_nitpicks",
    "agreement_reject",
    "borderline_reject_edits",
)


def build_report(db, run_id: int) -> dict[str, list[EmailDraft]]:
    """Read-only: bucket every verdicted draft in run_id into the critic<->Alex TASTE matrix."""
    drafts = (
        db.query(EmailDraft)
        .filter(EmailDraft.run_id == run_id, EmailDraft.alex_verdict.isnot(None))
        .order_by(EmailDraft.id.asc())
        .all()
    )
    return bucket_drafts(drafts)


def bucket_drafts(drafts) -> dict[str, list[EmailDraft]]:
    """Bucket already-verdicted drafts into the taste matrix + the outside-matrix rows. Split out
    from build_report so tests can exercise the bucketing logic without a DB (draft-shaped
    SimpleNamespace stand-ins)."""
    quadrants: dict[str, list[EmailDraft]] = {
        "agreement_pass": [],  # taste PASS, alex ok_as_is / ok_with_edits
        "critic_blind": [],  # taste PASS, alex would_not_send
        "critic_nitpicks": [],  # taste FAIL, alex ok_as_is
        "agreement_reject": [],  # taste FAIL, alex would_not_send
        "borderline_reject_edits": [],  # taste FAIL, alex ok_with_edits
        "cut_by_mechanics": [],  # no taste verdict — cut by mechanics before the rubric ran
        "no_taste_verdict": [],  # no taste verdict for another reason (no_vacancy / LLM off)
        "unrecognized_verdict": [],  # alex_verdict outside ALEX_VERDICTS — data hygiene
    }

    for d in drafts:
        verdict = d.alex_verdict
        if verdict not in ALEX_VERDICTS:
            quadrants["unrecognized_verdict"].append(d)
            continue
        taste_pass = d.critic_taste_pass
        if taste_pass is None:
            if d.generation_is_valid is False:
                quadrants["cut_by_mechanics"].append(d)
            else:
                quadrants["no_taste_verdict"].append(d)
            continue
        if taste_pass:
            if verdict == "would_not_send":
                quadrants["critic_blind"].append(d)
            else:  # ok_as_is or ok_with_edits
                quadrants["agreement_pass"].append(d)
        else:
            if verdict == "ok_as_is":
                quadrants["critic_nitpicks"].append(d)
            elif verdict == "would_not_send":
                quadrants["agreement_reject"].append(d)
            else:  # ok_with_edits
                quadrants["borderline_reject_edits"].append(d)

    return quadrants


def _line(d: EmailDraft) -> str:
    why = (d.alex_verdict_why or "")[:100]
    return (
        f"    draft_id={d.id} company={d.company!r} score={d.validation_score} "
        f"alex_verdict={d.alex_verdict!r} why={why!r}"
    )


def print_report(run_id: int, quadrants: dict[str, list[EmailDraft]]) -> None:
    total = sum(len(v) for v in quadrants.values())
    matrix_total = sum(len(quadrants[k]) for k in MATRIX_KEYS)
    print(f"=== critic vs Alex — run_id={run_id} ({total} drafts with a verdict) ===\n")

    print(f"Taste matrix (counts, {matrix_total} taste-evaluated drafts):")
    print(f"  agreement (taste pass, Alex ok):               {len(quadrants['agreement_pass'])}")
    print(f"  CRITIC BLIND (taste pass, Alex would-not-send): {len(quadrants['critic_blind'])}")
    print(f"  CRITIC NITPICKS (taste fail, Alex ok):          {len(quadrants['critic_nitpicks'])}")
    print(f"  agreement (taste fail, Alex would-not-send):    {len(quadrants['agreement_reject'])}")
    print(f"  borderline (taste fail, Alex ok_with_edits):    {len(quadrants['borderline_reject_edits'])}")

    print("\nOutside the matrix (no taste verdict):")
    print(f"  cut by mechanics (banned/invented_role/dup/template drift): {len(quadrants['cut_by_mechanics'])}")
    print(f"  no taste verdict (no_vacancy / LLM off):                    {len(quadrants['no_taste_verdict'])}")
    if quadrants["unrecognized_verdict"]:
        print(f"  unrecognized alex_verdict value (data hygiene):             {len(quadrants['unrecognized_verdict'])}")

    if matrix_total:
        agree = len(quadrants["agreement_pass"]) + len(quadrants["agreement_reject"])
        print(f"\n  Agreement rate (over the taste matrix only): {agree}/{matrix_total} ({100 * agree / matrix_total:.0f}%)")

    for key, label in (
        ("critic_blind", "\nCRITIC BLIND — taste passed it, Alex would not send:"),
        ("critic_nitpicks", "\nCRITIC NITPICKS — taste rejected it, Alex is fine with it:"),
        ("borderline_reject_edits", "\nBORDERLINE — taste rejected it, Alex ok with edits:"),
        ("cut_by_mechanics", "\nCUT BY MECHANICS — no taste verdict, mechanics rejected it:"),
        ("no_taste_verdict", "\nNO TASTE VERDICT — no_vacancy / LLM off:"),
        ("unrecognized_verdict", "\nUNRECOGNIZED alex_verdict value:"),
    ):
        rows = quadrants[key]
        if not rows:
            continue
        print(label)
        for d in rows:
            print(_line(d))


def main() -> int:
    run_id_arg = sys.argv[1] if len(sys.argv) > 1 else None
    db = SessionLocal()
    try:
        run_id = _resolve_run_id(db, run_id_arg)
        if run_id is None:
            print("No runs found in this database.", file=sys.stderr)
            return 1
        quadrants = build_report(db, run_id)
        print_report(run_id, quadrants)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
