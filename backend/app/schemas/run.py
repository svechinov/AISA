from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCompanyRow(BaseModel):
    collect_index: int
    name: str
    website: str
    contact_status: Literal[
        "found",
        "none",
        "pending",
        "no_email",
        "llm_error",
        "unknown",
    ]
    ai_fit_status: Literal["correct", "incorrect"] | None = None
    ai_fit_reason: str | None = None
    ai_fit_checked_at: str | None = None


class RunCompaniesRead(BaseModel):
    companies: list[RunCompanyRow]
    collect_step_status: str | None = None
    find_step_status: str | None = None
    companies_total: int = 0
    limit: int | None = None
    offset: int = 0


class RetryCompanyFindBody(BaseModel):
    collect_index: int = Field(ge=0)


class RetryCompanyFindResult(BaseModel):
    contacts_before: int
    contacts_after: int
    new_contacts_merged: int


class DeleteRunCompanyResult(BaseModel):
    deleted_collect_index: int
    contacts_removed: int


class AnalyzeCompanyFitBody(BaseModel):
    force: bool = False


class AnalyzeCompanyFitResult(BaseModel):
    collect_index: int
    ai_fit_status: Literal["correct", "incorrect"]
    ai_fit_reason: str
    ai_fit_checked_at: str


class AnalyzeFitPendingBody(BaseModel):
    max_rows: int = Field(default=200, ge=1, le=500)
    force: bool = False


class AnalyzeFitPendingResult(BaseModel):
    analyzed: int
    results: list[AnalyzeCompanyFitResult]
    errors: list[str]


class RunStart(BaseModel):
    project_id: int
    workflow_name: str = "generic_outreach"
    input_json: dict = Field(default_factory=dict)
    name: str | None = None
    notes: str | None = None
    segment: str | None = None
    # Primary: labeled textarea (Offer:/Target:/…); merged with legacy flat fields if empty.
    outreach_brief: str = ""
    product: str = ""
    target_entities: str = ""
    target_roles: str = ""
    outreach_goal: str = ""
    tone: str = "Professional"
    extra_context: str = ""


class RunEditFormRead(BaseModel):
    """Minimal payload for the New/Edit run dialog — avoids full RunRead (large context_json, master_email, etc.)."""

    id: int
    name: str | None = None
    notes: str | None = None
    segment: str | None = None
    email_style_mode: str | None = None
    outreach_brief: str = ""


class RunTrackingStripRead(BaseModel):
    """Human UI Tracking tab only: signature HTML + minimal ``context_json._human_ui`` (no full run row)."""

    sender_signature_html: str = ""
    context_json: dict = Field(default_factory=dict)


class RunRead(BaseModel):
    id: int
    project_id: int
    workflow_name: str
    status: str
    input_json: dict
    created_at: datetime
    finished_at: datetime | None
    name: str | None = None
    notes: str | None = None
    segment: str | None = None
    closed_at: datetime | None = None
    context_json: dict = Field(default_factory=dict)
    master_prompt: str | None = None
    master_email: dict | None = None
    master_email_subject: str | None = None
    master_email_body: str | None = None
    sender_signature_html: str | None = None
    #: Canonical prompt textarea (run_setups); empty when unset.
    prompt_setup_text: str | None = None
    email_style_mode: str | None = None

    class Config:
        from_attributes = True


def run_read_from_orm(run: Any) -> RunRead:
    """Serialize Run from relational stores + small scalars — never pulls legacy JSON blobs via ORM validation."""
    from sqlalchemy.orm import object_session

    from app.repositories.run_human_ui_repo import get_event_chain_collapsed_map
    from app.services.run_context_service import get_prompt_setup_text, get_sender_signature_html
    from app.utils.run_relational_payload import (
        effective_context_json_for_api,
        effective_input_json_for_api,
        effective_master_email_for_api,
    )

    pt = get_prompt_setup_text(run)
    sess = object_session(run)
    if sess is not None:
        ctx = effective_context_json_for_api(sess, run)
        chain = get_event_chain_collapsed_map(sess, run.id)
        if chain:
            ui = dict(ctx.get("_human_ui") or {})
            ui["event_chain_collapsed"] = chain
            ctx["_human_ui"] = ui
        return RunRead(
            id=run.id,
            project_id=run.project_id,
            workflow_name=run.workflow_name,
            status=run.status,
            input_json=effective_input_json_for_api(sess, run),
            created_at=run.created_at,
            finished_at=run.finished_at,
            name=run.name,
            notes=run.notes,
            segment=run.segment,
            closed_at=run.closed_at,
            context_json=ctx,
            master_prompt=getattr(run, "master_prompt", None),
            master_email=effective_master_email_for_api(sess, run),
            master_email_subject=getattr(run, "master_email_subject", None),
            master_email_body=getattr(run, "master_email_body", None),
            sender_signature_html=get_sender_signature_html(run),
            prompt_setup_text=pt if pt else None,
            email_style_mode=run.email_style_mode,
        )
    return RunRead(
        id=run.id,
        project_id=run.project_id,
        workflow_name=run.workflow_name,
        status=run.status,
        input_json={},
        created_at=run.created_at,
        finished_at=run.finished_at,
        name=run.name,
        notes=run.notes,
        segment=run.segment,
        closed_at=run.closed_at,
        context_json={},
        master_prompt=getattr(run, "master_prompt", None),
        master_email=None,
        master_email_subject=getattr(run, "master_email_subject", None),
        master_email_body=getattr(run, "master_email_body", None),
        sender_signature_html=get_sender_signature_html(run),
        prompt_setup_text=pt if pt else None,
        email_style_mode=run.email_style_mode,
    )


class RunSignaturePatch(BaseModel):
    signature_html: str = ""


class RunPromptSetupPatch(BaseModel):
    """Labeled brief textarea; stored in run_setups.prompt_setup_text."""
    prompt_setup_text: str = ""


class RunPromptSetupPatchResult(BaseModel):
    """Minimal PATCH response — avoids serializing full Run (large context_json / master_prompt)."""

    id: int
    prompt_setup_saved: bool


class RunSignaturePatchResult(BaseModel):
    """Minimal PATCH response — avoids serializing full Run row."""

    id: int
    sender_signature_configured: bool


class RunReviewSetupFieldsRead(BaseModel):
    """Tiny GET for Prompt setup + Signature dialogs — no full Run / context_json blob."""

    prompt_setup_editor_text: str
    sender_signature_html: str = ""
    prompt_setup_saved: bool
    sender_signature_configured: bool


class RunHumanUiPatch(BaseModel):
    """Human dashboard-only UI state; stored under context_json._human_ui (ignored by LLM brief)."""

    #: Merges into `_human_ui.event_chain_collapsed` — draft id (string) → collapsed (true = events hidden).
    event_chain_collapsed: dict[str, bool] | None = None


class RunEmailStylePatch(BaseModel):
    """Target professional profile for this run (see email_style_service — Auto uses contact role heuristics)."""

    email_style_mode: str | None = None


class RunOutreachPatch(BaseModel):
    """Update segment, wave notes, and labeled outreach brief on an existing run (same parsing as POST /runs/start)."""

    notes: str | None = None
    segment: str = ""
    outreach_brief: str = ""
    #: Optional: set in same request as brief (Edit run — one PATCH instead of two).
    email_style_mode: str | None = None


class RunProjectPatch(BaseModel):
    """Move run to another project (sidebar list is keyed by project_id)."""

    project_id: int = Field(..., ge=1)


class TotalPerformanceRead(BaseModel):
    """All runs/projects: outreach (max of drafts sent vs distinct `email_events` type sent) + reply drafts sent; plus reply events."""

    emails_sent: int
    emails_sent_24h: int
    replies: int


class RunCardRead(BaseModel):
    """Sidebar + Runs tab + Switch run — trimmed vs full RunRead (no workflow_name, master payloads, updated_at)."""

    id: int
    project_id: int
    name: str
    notes: str | None = None
    segment: str | None = None
    #: Orchestrator state — Human UI checks ``needs_review`` before workspace merge.
    status: str
    display_phase: str
    closed_at: datetime | None = None
    companies_count: int
    contacts_count: int
    emails_sent: int
    replies: int
    active_threads: int
    created_at: datetime
    #: Human UI: prompt setup text stored in run_setups (no heavy payload on list).
    prompt_setup_saved: bool = False
    #: Human UI: signature HTML has visible text (same idea as dashboard check).
    sender_signature_configured: bool = False


class RunWorkspaceRead(RunRead):
    display_phase: str
    setup_summary: dict[str, Any]
    #: Deprecated in UI; kept for API compatibility (empty list).
    setup_steps: list[dict[str, Any]]
    setup_state_message: str
    performance: dict[str, Any]
    conversations: dict[str, Any]
    #: Outreach + reply sends per UTC hour, last 24h; index 0 = oldest hour.
    hourly_sends_24h: list[int] = Field(default_factory=lambda: [0] * 24)


class HumanUiActivityInformer(BaseModel):
    """One line for the Human UI Activity panel (server-queued, drained on workspace GET)."""

    id: str
    text: str


class RunWorkspaceLiteRead(BaseModel):
    """Cheap refresh for dashboard poll: phase, setup counts, performance + conversation counters (no full run row / contacts / drafts)."""

    display_phase: str
    setup_state_message: str
    setup_summary: dict[str, Any]
    performance: dict[str, Any]
    conversations: dict[str, Any]
    hourly_sends_24h: list[int] = Field(default_factory=lambda: [0] * 24)
    activity_informers: list[HumanUiActivityInformer] = Field(default_factory=list)


class RunWorkspaceTickRead(BaseModel):
    """Background metrics poll: phase, setup_summary, performance, hourly sends chart (UTC)."""

    display_phase: str
    setup_state_message: str
    setup_summary: dict[str, Any]
    performance: dict[str, Any]
    hourly_sends_24h: list[int] = Field(default_factory=lambda: [0] * 24)
    activity_informers: list[HumanUiActivityInformer] = Field(default_factory=list)
