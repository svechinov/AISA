from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCompanyRow(BaseModel):
    collect_index: int
    name: str
    website: str
    contact_status: Literal["found", "none", "pending", "no_email", "llm_error"]


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
    """Serialize Run with prompt/signature from run_setups (legacy columns may be cleared)."""
    from sqlalchemy.orm import object_session

    from app.repositories.run_human_ui_repo import get_event_chain_collapsed_map
    from app.services.run_context_service import get_prompt_setup_text, get_sender_signature_html
    from app.utils.run_relational_payload import (
        effective_context_json_for_api,
        effective_input_json_for_api,
        effective_master_email_for_api,
    )

    rd = RunRead.model_validate(run)
    pt = get_prompt_setup_text(run)
    sess = object_session(run)
    if sess is not None:
        ctx = effective_context_json_for_api(sess, run)
        chain = get_event_chain_collapsed_map(sess, run.id)
        if chain:
            ui = dict(ctx.get("_human_ui") or {})
            ui["event_chain_collapsed"] = chain
            ctx["_human_ui"] = ui
        return rd.model_copy(
            update={
                "sender_signature_html": get_sender_signature_html(run),
                "prompt_setup_text": pt if pt else None,
                "context_json": ctx,
                "input_json": effective_input_json_for_api(sess, run),
                "master_email": effective_master_email_for_api(sess, run),
            },
        )
    ctx = dict(rd.context_json or {})
    return rd.model_copy(
        update={
            "sender_signature_html": get_sender_signature_html(run),
            "prompt_setup_text": pt if pt else None,
            "context_json": ctx,
        },
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
    """Default outbound email voice when role does not imply another style (see email_style_service)."""

    email_style_mode: str | None = None


class RunOutreachPatch(BaseModel):
    """Update segment, wave notes, and labeled outreach brief on an existing run (same parsing as POST /runs/start)."""

    notes: str | None = None
    segment: str = ""
    outreach_brief: str = ""


class RunProjectPatch(BaseModel):
    """Move run to another project (sidebar list is keyed by project_id)."""

    project_id: int = Field(..., ge=1)


class TotalPerformanceRead(BaseModel):
    """All runs/projects: outreach (max of drafts sent vs distinct `email_events` type sent) + reply drafts sent; plus reply events."""

    emails_sent: int
    emails_sent_24h: int
    replies: int


class RunCardRead(BaseModel):
    id: int
    project_id: int
    name: str
    notes: str | None = None
    segment: str | None = None
    workflow_name: str
    status: str
    display_phase: str
    closed_at: datetime | None = None
    companies_count: int
    contacts_count: int
    emails_sent: int
    replies: int
    active_threads: int
    updated_at: datetime | None = None
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


class RunWorkspaceLiteRead(BaseModel):
    """Cheap refresh for dashboard poll: phase, setup counts, performance + conversation counters (no full run row / contacts / drafts)."""

    display_phase: str
    setup_state_message: str
    setup_summary: dict[str, Any]
    performance: dict[str, Any]
    conversations: dict[str, Any]
    hourly_sends_24h: list[int] = Field(default_factory=lambda: [0] * 24)
