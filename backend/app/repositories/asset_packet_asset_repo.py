from sqlalchemy.orm import Session

from app.models.asset_packet_asset import AssetPacketAsset


def replace_asset_packet_asset_rows(db: Session, packet_id: int, assets_payload: list[dict]) -> None:
    """Replace junction rows for this packet; does not commit. Skips items without asset_id."""
    db.query(AssetPacketAsset).filter(AssetPacketAsset.packet_id == packet_id).delete(synchronize_session=False)
    for i, item in enumerate(assets_payload or []):
        if not isinstance(item, dict):
            continue
        aid = item.get("asset_id")
        if aid is None:
            continue
        try:
            aid_int = int(aid)
        except (TypeError, ValueError):
            continue
        db.add(AssetPacketAsset(packet_id=packet_id, asset_id=aid_int, position=i))


def copy_asset_packet_asset_rows(db: Session, from_packet_id: int, to_packet_id: int) -> None:
    """Copy junction rows after cloning a packet; does not commit."""
    rows = (
        db.query(AssetPacketAsset)
        .filter(AssetPacketAsset.packet_id == from_packet_id)
        .order_by(AssetPacketAsset.position.asc(), AssetPacketAsset.id.asc())
        .all()
    )
    for r in rows:
        db.add(
            AssetPacketAsset(
                packet_id=to_packet_id,
                asset_id=r.asset_id,
                position=r.position,
            ),
        )


def count_rows_for_packet(db: Session, packet_id: int) -> int:
    return db.query(AssetPacketAsset).filter(AssetPacketAsset.packet_id == packet_id).count()
