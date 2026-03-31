from datetime import datetime

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
    packet_json: dict
    created_at: datetime

    class Config:
        from_attributes = True


class AssetPacketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    packet_json: dict | None = None
    reply_draft_id: int | None = None


class AttachReplyDraftRequest(BaseModel):
    reply_draft_id: int


class AssetPacketAssetItem(BaseModel):
    """Snapshot row in packet_json.assets; extra keys are preserved on round-trip."""

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
