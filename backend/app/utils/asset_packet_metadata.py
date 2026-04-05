"""Asset packet metadata: entity_json_kv scope asset_packet (replaces asset_packets.packet_json)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.constants.entity_kv_scope import SCOPE_ASSET_PACKET
from app.models.asset_packet import AssetPacket
from app.utils.entity_kv_storage import get_kv_dict, replace_kv_dict


def effective_packet_metadata_dict(db: Session, packet: AssetPacket) -> dict[str, Any]:
    """Canonical metadata for API (no ``assets`` key — membership is asset_packet_assets)."""
    d = get_kv_dict(db, SCOPE_ASSET_PACKET, packet.id)
    if d:
        return {k: v for k, v in d.items() if k != "assets"}
    pj = dict(packet.packet_json or {})
    pj.pop("assets", None)
    if not pj:
        if dict(packet.packet_json or {}):
            packet.packet_json = {}
        return {}
    replace_kv_dict(db, SCOPE_ASSET_PACKET, packet.id, pj)
    packet.packet_json = {}
    return pj


def persist_packet_metadata_dict(db: Session, packet: AssetPacket, data: dict[str, Any] | None) -> None:
    """Write metadata to KV and clear legacy packet_json blob column."""
    clean = {k: v for k, v in dict(data or {}).items() if k != "assets"}
    replace_kv_dict(db, SCOPE_ASSET_PACKET, packet.id, clean if clean else None)
    packet.packet_json = {}
