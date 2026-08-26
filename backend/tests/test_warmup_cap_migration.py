"""DB-backed test for the one-time warm-up daily_cap repair (backlog B-013 §3). The old seed wrote
daily_cap=5 alongside a ramp targeting cap=25; since effective_daily_cap = min(daily_cap, ramp_cap),
that pair permanently clamped sending at 5/day and made the ramp dead code. Requires the
ai_biz_os_realrun.db snapshot (see conftest.py).

Mutates the single per-mailbox sending_policies row and restores it afterward — this table has one
row per mailbox (a singleton within the test-process snapshot), unlike the rest of the suite which
creates uniquely-named rows per test.
"""

from app.init_db import _fix_stale_warmup_daily_cap
from app.models.sending_policy import SendingPolicy


def test_fix_stale_warmup_daily_cap_repairs_the_old_bad_seed(db):
    policy = db.query(SendingPolicy).first()
    if policy is None:
        import pytest

        pytest.skip("no sending_policies row on this snapshot")

    original_cap = policy.daily_cap
    original_ramp = dict(policy.warmup_ramp_json or {})
    try:
        policy.daily_cap = 5
        policy.warmup_ramp_json = {**original_ramp, "start": 5, "step_per_week": 5, "cap": 25}
        db.add(policy)
        db.commit()

        _fix_stale_warmup_daily_cap()

        db.refresh(policy)
        assert policy.daily_cap == 25
    finally:
        policy.daily_cap = original_cap
        policy.warmup_ramp_json = original_ramp
        db.add(policy)
        db.commit()


def test_fix_stale_warmup_daily_cap_leaves_deliberate_low_cap_alone(db):
    policy = db.query(SendingPolicy).first()
    if policy is None:
        import pytest

        pytest.skip("no sending_policies row on this snapshot")

    original_cap = policy.daily_cap
    original_ramp = dict(policy.warmup_ramp_json or {})
    try:
        # A deliberately-lowered cap where the ramp ceiling ISN'T 25 must not be touched — only the
        # exact stale (daily_cap=5, ramp.cap=25) pair from the old seed is repaired.
        policy.daily_cap = 3
        policy.warmup_ramp_json = {**original_ramp, "cap": 3}
        db.add(policy)
        db.commit()

        _fix_stale_warmup_daily_cap()

        db.refresh(policy)
        assert policy.daily_cap == 3
    finally:
        policy.daily_cap = original_cap
        policy.warmup_ramp_json = original_ramp
        db.add(policy)
        db.commit()
