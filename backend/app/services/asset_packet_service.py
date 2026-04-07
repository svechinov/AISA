from copy import deepcopy

from sqlalchemy.orm import Session

from app.models.asset_packet import AssetPacket
from app.models.asset_packet_asset import AssetPacketAsset
from app.repositories.asset_packet_asset_repo import (
    copy_asset_packet_asset_rows,
    replace_asset_packet_asset_rows,
)
from app.repositories.asset_packet_repo import (
    create_asset_packet,
    get_asset_packet,
    list_asset_packets_by_thread,
)
from app.repositories.asset_repo import get_asset, list_assets
from app.repositories.contact_repo import get_contact
from app.repositories.email_thread_repo import get_email_thread
from app.repositories.run_repo import get_run
from app.utils.asset_packet_metadata import effective_packet_metadata_dict, persist_packet_metadata_dict


def _ref_dict_from_asset_row(asset) -> dict:
    """Snapshot shape expected by email body / UI — built from ``assets`` table only."""
    return {
        "asset_id": asset.id,
        "title": asset.name,
        "asset_type": asset.asset_type,
        "name": asset.name,
        "description": asset.description,
        "url": asset.url,
        "file_path": asset.file_path,
        "download_url": asset.download_url,
        "storage_key": asset.storage_key,
        "filename": asset.filename,
        "mime_type": asset.mime_type,
        "file_size_bytes": asset.file_size_bytes,
    }


def get_ordered_asset_refs_for_packet(db: Session, packet: AssetPacket) -> list[dict]:
    """Membership/order: ``asset_packet_assets`` + ``assets`` rows only (no packet_json.assets)."""
    pid = getattr(packet, "id", None)
    if pid is None:
        return []
    rows = (
        db.query(AssetPacketAsset)
        .filter(AssetPacketAsset.packet_id == pid)
        .order_by(AssetPacketAsset.position.asc(), AssetPacketAsset.id.asc())
        .all()
    )
    if not rows:
        return []
    out: list[dict] = []
    for r in rows:
        a = get_asset(db, r.asset_id)
        if a:
            out.append(_ref_dict_from_asset_row(a))
        else:
            out.append({"asset_id": r.asset_id})
    return out


def packet_metadata_json_for_api(db: Session, packet: AssetPacket) -> dict:
    """Metadata only for API ``packet_json`` (no ``assets`` key — membership is ``AssetPacketRead.assets``)."""
    return effective_packet_metadata_dict(db, packet)


def render_assets_block_for_email(assets: list[dict]) -> str:
    """Build Materials: block for link-only asset rows (not sent as MIME attachments)."""
    if not assets:
        return ""

    lines = ["", "Materials:", ""]

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        title = asset.get("title") or asset.get("name") or asset.get("asset_type") or "Asset"
        url = asset.get("url") or asset.get("file_url") or asset.get("file_path") or ""
        asset_type = asset.get("asset_type") or asset.get("type") or ""

        if url and asset_type:
            lines.append(f"- {title} ({asset_type}): {url}")
        elif url:
            lines.append(f"- {title}: {url}")
        else:
            lines.append(f"- {title}")

    return "\n".join(lines)


def render_packet_block_for_email(db: Session, packet: AssetPacket | None) -> str:
    """Full packet → Materials block for every asset row (no attachment split)."""
    if not packet or packet.status == "archived":
        return ""
    assets = get_ordered_asset_refs_for_packet(db, packet)
    return render_assets_block_for_email(assets)


def validate_packet_assets_payload(db: Session, assets_payload: list[dict]) -> None:
    seen: set[int] = set()
    for item in assets_payload:
        if not isinstance(item, dict):
            raise ValueError("Each packet asset must be an object")
        asset_id = item.get("asset_id")
        if asset_id is None:
            continue
        try:
            aid = int(asset_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid asset_id: {asset_id}") from e
        if aid in seen:
            raise ValueError(f"Duplicate asset in packet: {aid}")
        seen.add(aid)
        asset = get_asset(db, aid)
        if not asset:
            raise ValueError(f"Asset not found: {aid}")
        if asset.status != "active":
            raise ValueError(f"Asset {aid} is not active")


def update_packet_assets(db: Session, packet_id: int, assets_payload: list[dict]) -> AssetPacket:
    packet = get_asset_packet(db, packet_id)
    if not packet:
        raise ValueError("Asset packet not found")

    if packet.status == "archived":
        raise ValueError("Archived packet cannot be edited")

    if packet.status not in {"draft", "approved"}:
        raise ValueError("Only draft or approved packets can be edited")

    validate_packet_assets_payload(db, assets_payload)

    replace_asset_packet_asset_rows(db, packet.id, assets_payload)
    meta = effective_packet_metadata_dict(db, packet)
    persist_packet_metadata_dict(db, packet, meta)

    db.add(packet)
    db.commit()
    db.refresh(packet)
    return packet


def lock_packet_after_send(db: Session, packet_id: int) -> AssetPacket:
    """After successful reply send: freeze packet mutations (status → sent). Idempotent if already sent."""
    packet = get_asset_packet(db, packet_id)
    if not packet:
        raise ValueError("Asset packet not found")

    if packet.status == "archived":
        raise ValueError("Archived packet cannot be locked")

    if packet.status == "sent":
        return packet

    if packet.status not in {"draft", "approved"}:
        raise ValueError(f"Packet cannot be locked from status: {packet.status}")

    packet.status = "sent"
    db.add(packet)
    db.commit()
    db.refresh(packet)
    return packet


def clone_asset_packet(db: Session, packet_id: int) -> AssetPacket:
    """Read-only on original: new row, draft, no reply_draft_id, deep-copied packet_json snapshot."""
    original = get_asset_packet(db, packet_id)
    if not original:
        raise ValueError("Asset packet not found")

    base_title = (original.title or "").strip() or "Packet"
    new_title = f"{base_title} (copy)"

    pj = effective_packet_metadata_dict(db, original)
    new_packet = AssetPacket(
        run_id=original.run_id,
        thread_id=original.thread_id,
        contact_id=original.contact_id,
        packet_type=original.packet_type,
        title=new_title,
        description=original.description,
        status="draft",
        packet_json={},
        reply_draft_id=None,
    )

    db.add(new_packet)
    db.flush()
    persist_packet_metadata_dict(db, new_packet, pj)
    copy_asset_packet_asset_rows(db, original.id, new_packet.id)
    db.commit()
    db.refresh(new_packet)
    return new_packet


def create_run_asset_packet(
    db: Session,
    run_id: int,
    title: str,
    assets_payload: list[dict],
) -> AssetPacket:
    if not get_run(db, run_id):
        raise ValueError(f"Run {run_id} not found")

    validate_packet_assets_payload(db, assets_payload)
    packet = create_asset_packet(
        db=db,
        run_id=run_id,
        thread_id=None,
        contact_id=None,
        packet_type="preset",
        title=title.strip() or "Packet",
        description=None,
        status="draft",
        packet_json={"source": "run_preset"},
        reply_draft_id=None,
    )
    replace_asset_packet_asset_rows(db, packet.id, assets_payload)
    db.commit()
    db.refresh(packet)
    return packet


def build_asset_packet_for_thread(db: Session, thread_id: int) -> dict:
    thread = get_email_thread(db, thread_id)
    if not thread:
        raise ValueError(f"Thread {thread_id} not found")

    classification = thread.classification
    if classification not in {"need_more_info", "interested"}:
        raise ValueError("Asset packets are only supported for need_more_info or interested threads")

    existing_packets = list_asset_packets_by_thread(db, thread_id)
    for packet in existing_packets:
        if packet.packet_type == classification and packet.status in {"draft", "approved"}:
            return {
                "thread_id": thread.id,
                "packet_id": packet.id,
                "deduplicated": True,
            }

    contact = get_contact(db, thread.contact_id)
    assets = list_assets(db, status="active")

    selected_assets = []
    for asset in assets:
        if classification == "need_more_info" and asset.asset_type in {"deck", "one_pager", "website"}:
            selected_assets.append(asset)
        elif classification == "interested" and asset.asset_type in {"deck", "screener", "catalog", "website"}:
            selected_assets.append(asset)

    packet_json = {
        "classification": classification,
        "contact": {
            "name": contact.name if contact else None,
            "company": contact.company if contact else None,
            "email": contact.email if contact else None,
        },
    }
    assets_payload = [_ref_dict_from_asset_row(a) for a in selected_assets]

    packet = create_asset_packet(
        db=db,
        run_id=thread.run_id,
        thread_id=thread.id,
        contact_id=thread.contact_id,
        packet_type=classification,
        title=f"{classification.replace('_', ' ').title()} packet",
        description=f"Materials packet for thread #{thread.id}",
        status="draft",
        packet_json=packet_json,
    )
    replace_asset_packet_asset_rows(db, packet.id, assets_payload)
    db.commit()
    db.refresh(packet)

    return {
        "thread_id": thread.id,
        "packet_id": packet.id,
        "deduplicated": False,
    }
