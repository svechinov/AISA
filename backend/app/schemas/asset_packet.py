from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssetPacketRead(BaseModel):
    id: int
    run_id: int
    thread_id: int | None
    contact_id: int | None
    reply_draft_id: int | None
    packet_type: str
    title: str
    description: str | None
    status: str
    #: Ordered snapshots from ``asset_packet_assets`` + ``assets`` table rows (not from ``packet_json``).
    assets: list[dict[str, Any]] = Field(default_factory=list)
    #: Metadata only (no embedded ``assets`` list).
    packet_json: dict
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_packet(cls, db, packet) -> "AssetPacketRead":
        from app.services.asset_packet_service import (
            get_ordered_asset_refs_for_packet,
            packet_metadata_json_for_api,
        )

        return cls(
            id=packet.id,
            run_id=packet.run_id,
            thread_id=packet.thread_id,
            contact_id=packet.contact_id,
            reply_draft_id=packet.reply_draft_id,
            packet_type=packet.packet_type,
            title=packet.title,
            description=packet.description,
            status=packet.status,
            assets=get_ordered_asset_refs_for_packet(db, packet),
            packet_json=packet_metadata_json_for_api(packet),
            created_at=packet.created_at,
        )


class AssetPacketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    packet_json: dict | None = None
    reply_draft_id: int | None = None


class AttachReplyDraftRequest(BaseModel):
    reply_draft_id: int


class AssetPacketAssetItem(BaseModel):
    """Library asset snapshot for create/update; persisted via ``asset_packet_assets`` + ``assets`` rows."""

    model_config = ConfigDict(extra="allow")

    asset_id: int | None = None
    title: str | None = None
    name: str | None = None
    description: str | None = None
    asset_type: str | None = None
    url: str | None = None
    file_path: str | None = None
    download_url: str | None = None
    storage_key: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None


class UpdateAssetPacketAssetsRequest(BaseModel):
    assets: list[AssetPacketAssetItem]


class CreateRunAssetPacketRequest(BaseModel):
    """Run-level preset (no thread). Contents are merged into drafts via asset ids in the UI."""

    title: str
    assets: list[AssetPacketAssetItem] = Field(default_factory=list)
