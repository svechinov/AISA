"""B-147: seed Alexey's Cyprus segment 2 (Limassol) closing-paragraph with variants A/B/C/D for
rotation at generation time (email_finale_templates.get_finale_variants / pick_finale_variant_index).

ONE-OFF, NOT part of the regular canon sync (seed_alexstaff_preset.py) — this touches exactly one
field on the live "alexey" persona row: finales_json.segments.limassol.variants.en, converting it
from a bare string (today's single finale) into a 4-item list:
  [0] A = the current finale, verbatim, UNCHANGED — read from the DB row, not hardcoded here, so
      this script cannot silently overwrite it with stale text.
  [1] B = Alexey's 2026-07-20 revision: "Would you have 15 minutes for a call? Or, if you happen
      to be in Limassol or Paphos, a coffee, or Malindi on a Wednesday."
  [2] C = "I co-founded the agency and I'm based on Cyprus. If you happen to be in Limassol or
      Paphos, coffee is on me. Or we could meet at the Malindi IT party any Wednesday. Or would a
      quick 15-minute call be easier?"
  [3] D = Alexey's verbatim from the Joyteractive letter, 2026-07-21: "I co-founded the agency and
      I'm based on Cyprus. Would a quick 15-minute call work? And if you're ever in Cyprus - coffee
      is on me, or the Malindi IT party any Wednesday. Shall we meet?"

Segment choice — CONFIRM before applying: "limassol" (segment 2). B/C/D all offer Limassol/Cyprus
coffee plus the Malindi Wednesday meetup, which matches segment 2's existing content pattern
("I live in Paphos but I'm in Limassol most weeks ... or we could catch each other any Wednesday at
the iT_Party at Malindi") far more closely than segment 1 (Paphos-only, no Malindi in that text) or
segments 3/4. If segment 2 is not what was meant, edit SEGMENT_KEY below before running --apply.

Only the "en" key is touched. "ru", "en_no_malindi", "ru_no_malindi" are untouched — B/C/D all
mention Malindi explicitly and would be wrong for a no-Malindi reply.

HARD RULE 19 note (seed_alexstaff_preset.py): variants C and D both open with "I co-founded the
agency and I'm based on Cyprus" — a self-introduction. If a draft rotates onto finale_variant=2 or
3, the generator must not ALSO write "I co-founded the agency" in the body (exactly once per email,
body OR finale).

--dry-run prints a diff of the current value vs the target A/B/C/D list and writes nothing (default
behavior mirrors scripts/seed_alexstaff_preset.py — always read the diff before dropping the flag).

Usage (prod, per CLAUDE.md "Грабли" — scripts/ is not baked into the image):
    scp backend/scripts/seed_b147_alexey_cyprus_finale_variants.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_b147_alexey_cyprus_finale_variants.py --dry-run'
    # review the diff; only if it looks right:
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_b147_alexey_cyprus_finale_variants.py'
    ssh bizos 'rm ~/ai-biz-os/infra/data/seed_b147_alexey_cyprus_finale_variants.py'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.services.persona_service import ALEXEY_SLUG  # noqa: E402

SEGMENT_KEY = "limassol"
VARIANT_KEY = "en"

VARIANT_B = (
    "Would you have 15 minutes for a call? Or, if you happen to be in Limassol or Paphos, "
    "a coffee, or Malindi on a Wednesday."
)
VARIANT_C = (
    "I co-founded the agency and I'm based on Cyprus. If you happen to be in Limassol or Paphos, "
    "coffee is on me. Or we could meet at the Malindi IT party any Wednesday. Or would a quick "
    "15-minute call be easier?"
)
VARIANT_D = (
    "I co-founded the agency and I'm based on Cyprus. Would a quick 15-minute call work? And if "
    "you're ever in Cyprus - coffee is on me, or the Malindi IT party any Wednesday. Shall we meet?"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--dry-run", action="store_true", help="Print the target A/B/C/D list vs current; write nothing.",
    )
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        persona = db.query(Persona).filter(Persona.slug == ALEXEY_SLUG).first()
        if not persona:
            print(f"ERROR: no persona row with slug={ALEXEY_SLUG!r} — nothing to seed.")
            sys.exit(1)

        # Deep-copy BEFORE mutating: SQLAlchemy's plain (non-Mutable) JSON column does not detect
        # in-place mutation of the same dict object, even followed by `persona.finales_json = finales`
        # — that reassignment is a no-op if `finales` is still the identical object. A fresh copy
        # guarantees the final assignment is seen as a real change and gets committed.
        import copy

        finales = copy.deepcopy(persona.finales_json) if persona.finales_json else {}
        segments = finales.get("segments") or {}
        seg = segments.get(SEGMENT_KEY)
        if not seg:
            print(f"ERROR: segment {SEGMENT_KEY!r} not found in persona.finales_json — aborting.")
            sys.exit(1)
        variants = seg.get("variants") or {}
        current = variants.get(VARIANT_KEY)
        if not isinstance(current, str) or not current:
            print(
                f"ERROR: finales_json.segments.{SEGMENT_KEY}.variants.{VARIANT_KEY} is not a "
                f"non-empty string (got {current!r}) — refusing to guess variant A; aborting."
            )
            sys.exit(1)

        target = [current, VARIANT_B, VARIANT_C, VARIANT_D]

        print(f"persona: {persona.slug} (id={persona.id})")
        print(f"segment: {SEGMENT_KEY}   variant key: {VARIANT_KEY}")
        print("\n--- current (single string, becomes variant A / index 0) ---")
        print(current)
        print("\n--- target list (A / B / C / D) ---")
        for i, t in enumerate(target):
            print(f"[{i}] {t}")

        if args.dry_run:
            print("\nDry run; no changes. Re-run without --dry-run to write.")
            return

        variants[VARIANT_KEY] = target
        seg["variants"] = variants
        segments[SEGMENT_KEY] = seg
        finales["segments"] = segments
        persona.finales_json = finales
        db.add(persona)
        db.commit()
        print("\nApplied.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
