"""Shared pagination metadata for list endpoints."""

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
