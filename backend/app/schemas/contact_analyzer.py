from datetime import datetime

from pydantic import BaseModel, Field


class ContactAnalyzerRowRead(BaseModel):
    email: str
    email_normalized: str
    contact_ids: list[int]
    gmail_history_status: str | None = None
    gmail_history_checked_at: datetime | None = None
    gmail_inbox_imported_at: datetime | None = None


class ContactAnalyzerListResponse(BaseModel):
    run_id: int
    rows: list[ContactAnalyzerRowRead]


class ContactAnalyzerVerifyBody(BaseModel):
    email_normalized: str = Field(..., min_length=3, description="Lowercase normalized email key from list")


class ContactAnalyzerVerifyResponse(BaseModel):
    email_normalized: str
    gmail_history_status: str


class ContactAnalyzerVerifyAllResponse(BaseModel):
    verified: int
    failures: list[dict]


class ContactAnalyzerImportInboxBody(BaseModel):
    email_normalized: str = Field(..., min_length=3)


class ContactAnalyzerImportInboxResponse(BaseModel):
    email_normalized: str
    listed: int
    imported: int
    skipped_existing: int
