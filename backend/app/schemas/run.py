from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


class RunWorkspaceRead(RunRead):
    display_phase: str
    setup_summary: dict[str, Any]
    setup_steps: list[dict[str, Any]]
    setup_state_message: str
    performance: dict[str, Any]
    conversations: dict[str, Any]
