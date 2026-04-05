"""Dashboard + orchestrator thresholds for outreach setup (companies → contacts → validation)."""

SETUP_MILESTONE_COMPANIES = 20
SETUP_MILESTONE_CONTACTS = 15
SETUP_MILESTONE_VALID_CONTACTS = 10
SETUP_ACCUMULATION_MAX_ROUNDS = 50
# After all three milestones are true, keep this many extra collect/find/validate cycles (same pass).
SETUP_EXTRA_ROUNDS_AFTER_MILESTONES = 2

# First-time setup: stop if (companies, contacts, valid) counts unchanged this many rounds in a row.
SETUP_STALL_LIMIT_DEFAULT = 2

# POST /runs/:id/restart — "Continue outreach": keep accumulating; looser exit than first-time setup.
CONTINUE_OUTREACH_MIN_ROUNDS = 5
CONTINUE_OUTREACH_STALL_LIMIT = 6
