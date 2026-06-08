import logging

logger = logging.getLogger(__name__)

# Legacy status-based background loop (LeadGen lineage) — DISABLED 2026-06-08.
#
# It ran tavily_dossier_agent + fg_profiler_agent on contacts in ai_pipeline_status='needs_osint'.
# Problems: (1) fg_profiler is a *rival* email generator (writes raw-markdown drafts via Gemini —
# no key on VDS) competing with the canonical outreach_email_pipeline; (2) nothing sets contacts
# to 'needs_osint' except a manual per-contact endpoint, so the loop spun idle and spammed logs.
#
# OSINT is now part of the step-based pipeline (enrich_crm_data, wired into run_workflow and the
# AmoCRM import). See engine_reconciliation_plan: the status-based path is being retired; person-
# level OSINT (Agent B -> person_osint) is the planned replacement for the personal hook.


async def leadgen_background_orchestrator():
    """Disabled no-op (kept for the main.py lifespan import). See module docstring above."""
    logger.info("LeadGen background orchestrator is DISABLED (OSINT moved to step pipeline).")
    return

