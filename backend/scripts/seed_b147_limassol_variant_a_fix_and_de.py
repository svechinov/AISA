"""B-147 continued (2026-07-21, canon iteration #2): two changes to the live "alexey" persona row's
finales_json.segments.limassol.variants.en list (currently 4 items, A-D, seeded 2026-07-20/21 by
scripts/seed_b147_alexey_cyprus_finale_variants.py):

1. Fix variant A's wording (index 0): "I'm in Limassol most weeks" -> "I'm often in Limassol"
   (Alexey's approved wording, canon iteration #2, item 6) — persona_service.py's code-level
   default was already fixed in this same session, but the LIVE DB row still has the OLD wording
   from when it was first seeded, and code changes don't retroactively touch already-seeded rows.
2. Append two new variants:
   [4] D(д) = "I'm one of the agency's founders. I live in Paphos and I'm often in Limassol. I'd
       be happy to drop by for a coffee - to meet and talk about how we could work together. Or
       we could just have a quick 15-minute call. What works best for you?"
   [5] E(е) = "I co-founded the agency. I live in Paphos and I'm in Limassol almost every week -
       we could meet for a coffee, get to know each other and see how we could work together. Or
       just a quick 15-minute call. What works best for you?"

Result: 6 byte-exact variants (A-E... six total) for limassol/en/malindi=True. Only that one slot
is touched — "ru", "en_no_malindi", "ru_no_malindi", and every other segment (paphos,
larnaca_nicosia, cyprus_other, outside) and persona (stepan) are untouched.

Idempotent: safe to re-run — if variant A already has the new wording and D/E are already present,
this is a no-op (dry-run and apply both just re-confirm the already-correct state).

--dry-run prints a diff of the current list vs the target list and writes nothing (mirrors
scripts/seed_alexstaff_preset.py's convention — always read the diff before dropping the flag).

Usage (prod, per CLAUDE.md "Грабли" — scripts/ is not baked into the image):
    scp backend/scripts/seed_b147_limassol_variant_a_fix_and_de.py bizos:~/ai-biz-os/infra/data/
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_b147_limassol_variant_a_fix_and_de.py --dry-run'
    # review the diff; only if it looks right:
    ssh bizos 'docker exec ai-biz-os-backend python3 /app/data/seed_b147_limassol_variant_a_fix_and_de.py'
    ssh bizos 'rm ~/ai-biz-os/infra/data/seed_b147_limassol_variant_a_fix_and_de.py'
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.init_db import ensure_schema  # noqa: E402
from app.models.persona import Persona  # noqa: E402
from app.services.persona_service import ALEXEY_SLUG  # noqa: E402

SEGMENT_KEY = "limassol"
VARIANT_KEY = "en"

OLD_WORDING_FRAGMENT = "I'm in Limassol most weeks"
NEW_WORDING_FRAGMENT = "I'm often in Limassol"

VARIANT_D = (
    "I'm one of the agency's founders. I live in Paphos and I'm often in Limassol. I'd be happy "
    "to drop by for a coffee - to meet and talk about how we could work together. Or we could "
    "just have a quick 15-minute call. What works best for you?"
)
VARIANT_E = (
    "I co-founded the agency. I live in Paphos and I'm in Limassol almost every week - we could "
    "meet for a coffee, get to know each other and see how we could work together. Or just a "
    "quick 15-minute call. What works best for you?"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--dry-run", action="store_true", help="Print the target list vs current; write nothing.",
    )
    args = ap.parse_args()

    ensure_schema()
    db = SessionLocal()
    try:
        persona = db.query(Persona).filter(Persona.slug == ALEXEY_SLUG).first()
        if not persona:
            print(f"ERROR: no persona row with slug={ALEXEY_SLUG!r} — nothing to seed.")
            sys.exit(1)

        finales = copy.deepcopy(persona.finales_json) if persona.finales_json else {}
        segments = finales.get("segments") or {}
        seg = segments.get(SEGMENT_KEY)
        if not seg:
            print(f"ERROR: segment {SEGMENT_KEY!r} not found in persona.finales_json — aborting.")
            sys.exit(1)
        variants = seg.get("variants") or {}
        current = variants.get(VARIANT_KEY)
        if not isinstance(current, list) or not current:
            print(
                f"ERROR: finales_json.segments.{SEGMENT_KEY}.variants.{VARIANT_KEY} is not a "
                f"non-empty list (got {current!r}) — expected the 4-item A-D list seeded earlier; aborting."
            )
            sys.exit(1)

        target = list(current)

        # Step 1: fix variant A's wording (index 0) if it still has the old phrasing.
        if OLD_WORDING_FRAGMENT in target[0]:
            target[0] = target[0].replace(OLD_WORDING_FRAGMENT, NEW_WORDING_FRAGMENT)
        elif NEW_WORDING_FRAGMENT not in target[0]:
            print(
                f"ERROR: variant A (index 0) contains neither the old nor the new wording fragment "
                f"— refusing to guess. Current text: {target[0]!r}"
            )
            sys.exit(1)

        # Step 2: append D and E if not already present (idempotent re-run).
        if VARIANT_D not in target:
            target.append(VARIANT_D)
        if VARIANT_E not in target:
            target.append(VARIANT_E)

        print(f"persona: {persona.slug} (id={persona.id})")
        print(f"segment: {SEGMENT_KEY}   variant key: {VARIANT_KEY}")
        print(f"\n--- current ({len(current)} variants) ---")
        for i, t in enumerate(current):
            print(f"[{i}] {t}")
        print(f"\n--- target ({len(target)} variants) ---")
        for i, t in enumerate(target):
            print(f"[{i}] {t}")

        if target == current:
            print("\nAlready up to date — no change needed.")
            if args.dry_run:
                return
            return

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
