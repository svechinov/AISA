from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCompanyRow(BaseModel):
    collect_index: int
    name: str
    website: str
    contact_status: Literal["found", "none", "pending", "no_email"]


class RunCompaniesRead(BaseModel):
    companies: list[RunCompanyRow]
    collect_step_status: str | None = None
    find_step_status: str | None = None


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

    class Config:
        from_attributes = True


class RunSignaturePatch(BaseModel):
    signature_html: str = ""


class RunPromptSetupPatch(BaseModel):
    """Labeled brief textarea (Offer/Target/Roles/…); stored under context_json.prompt_setup_text."""
    prompt_setup_text: str = ""


class RunHumanUiPatch(BaseModel):
    """Human dashboard-only UI state; stored under context_json._human_ui (ignored by LLM brief)."""

    #: Merges into `_human_ui.event_chain_collapsed` — draft id (string) → collapsed (true = events hidden).
    event_chain_collapsed: dict[str, bool] | None = None


class RunOutreachPatch(BaseModel):
    """Update segment, wave notes, and labeled outreach brief on an existing run (same parsing as POST /runs/start)."""

    notes: str | None = None
    segment: str = ""
    outreach_brief: str = ""


class TotalPerformanceRead(BaseModel):
    """All runs/projects: outreach (max of drafts sent vs distinct `email_events` type sent) + reply drafts sent."""

    emails_sent: int
    emails_sent_24h: int


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
    #: Human UI: prompt setup textarea saved under context_json (no heavy payload on list).
    prompt_setup_saved: bool = False
    #: Human UI: signature HTML has visible text (same idea as dashboard check).
    sender_signature_configured: bool = False


class RunWorkspaceRead(RunRead):
    display_phase: str
    setup_summary: dict[str, Any]
    setup_steps: list[dict[str, Any]]
    setup_state_message: str
    performance: dict[str, Any]
    conversations: dict[str, Any]


class RunWorkspaceLiteRead(BaseModel):
    """Cheap refresh for dashboard poll: phase, messages, performance + conversation counters only (no setup breakdown)."""

    display_phase: str
    setup_state_message: str
    performance: dict[str, Any]
    conversations: dict[str, Any]
