"""Asset metadata: entity_json_kv scope asset_metadata (replaces assets.metadata_json)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_ASSET_METADATA
from app.models.asset import Asset
from app.utils.entity_kv_storage import absorb_legacy_kv_into_scope, replace_kv_dict


def effective_asset_metadata_dict(db: Session, asset: Asset) -> dict[str, Any]:
    return absorb_legacy_kv_into_scope(
        db,
        SCOPE_ASSET_METADATA,
        asset.id,
        asset.metadata_json,
        clear_legacy=lambda: setattr(asset, "metadata_json", {}),
    )


def persist_asset_metadata_dict(db: Session, asset: Asset, data: dict[str, Any] | None) -> None:
    replace_kv_dict(db, SCOPE_ASSET_METADATA, asset.id, data or None)
    asset.metadata_json = {}
