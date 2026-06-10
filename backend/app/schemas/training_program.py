from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TrainingProgramCreate(BaseModel):
    name: str
    description: str | None = None
    target_pains: list[str] = []
    audience: str | None = None
    format: str | None = None
    bullets: list[str] = []
    asset_id: int | None = None
    status: str = "active"


class TrainingProgramUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    target_pains: list[str] | None = None
    audience: str | None = None
    format: str | None = None
    bullets: list[str] | None = None
    asset_id: int | None = None
    status: str | None = None


class TrainingProgramRead(BaseModel):
    id: int
    name: str
    description: str | None
    target_pains: list
    audience: str | None
    format: str | None
    bullets: list
    asset_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
