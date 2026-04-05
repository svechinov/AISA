from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.asset import Asset


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


def build_asset_read(db: Session, asset: Asset) -> AssetRead:
    from app.utils.asset_metadata import effective_asset_metadata_dict

    meta = effective_asset_metadata_dict(db, asset)
    return AssetRead(
        id=asset.id,
        asset_type=asset.asset_type,
        name=asset.name,
        description=asset.description,
        url=asset.url,
        file_path=asset.file_path,
        download_url=asset.download_url,
        storage_key=asset.storage_key,
        filename=asset.filename,
        mime_type=asset.mime_type,
        file_size_bytes=asset.file_size_bytes,
        status=asset.status,
        metadata_json=meta,
        created_at=asset.created_at,
    )
