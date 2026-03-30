"""Normalize draft.attached_asset_ids JSON to a deduped list of ints (order preserved)."""


def normalize_attached_asset_ids(raw: object) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    seen: set[int] = set()
    for x in raw:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out
