from datetime import datetime

from pydantic import BaseModel


class AssetCreate(BaseModel):
    asset_type: str
    name: str
    description: str | None = None
    url: str | None = None
    file_path: str | None = None
    download_url: str | None = None
    storage_key: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    status: str = "active"
    metadata_json: dict | None = None


class AssetRead(BaseModel):
    id: int
    asset_type: str
    name: str
    description: str | None
    url: str | None
    file_path: str | None
    download_url: str | None
    storage_key: str | None
    filename: str | None
    mime_type: str | None
    file_size_bytes: int | None
    status: str
    metadata_json: dict
    created_at: datetime

    class Config:
        from_attributes = True
