from sqlalchemy.orm import Session

from app.models.asset_packet import AssetPacket
from app.models.reply_draft import ReplyDraft


def create_asset_packet(
    db: Session,
    run_id: int,
    packet_type: str,
    title: str,
    description: str | None = None,
    thread_id: int | None = None,
    contact_id: int | None = None,
    reply_draft_id: int | None = None,
    status: str = "draft",
    packet_json: dict | None = None,
) -> AssetPacket:
    packet = AssetPacket(
        run_id=run_id,
        packet_type=packet_type,
        title=title,
        description=description,
        thread_id=thread_id,
        contact_id=contact_id,
        reply_draft_id=reply_draft_id,
        status=status,
        packet_json=packet_json or {},
    )
    db.add(packet)
    db.commit()
    db.refresh(packet)
    return packet


def get_asset_packet(db: Session, packet_id: int) -> AssetPacket | None:
    return db.query(AssetPacket).filter(AssetPacket.id == packet_id).first()


def get_packet_by_reply_draft_id(db: Session, reply_draft_id: int) -> AssetPacket | None:
    rows = (
        db.query(AssetPacket)
        .filter(AssetPacket.reply_draft_id == reply_draft_id)
        .order_by(AssetPacket.id.asc())
        .all()
    )
    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(
            f"Integrity error: multiple asset packets reference reply_draft_id={reply_draft_id}",
        )
    return rows[0]


def list_asset_packets_by_run(db: Session, run_id: int) -> list[AssetPacket]:
    return (
        db.query(AssetPacket)
        .filter(AssetPacket.run_id == run_id)
        .order_by(AssetPacket.id.desc())
        .all()
    )


def list_asset_packets_by_thread(db: Session, thread_id: int) -> list[AssetPacket]:
    return (
        db.query(AssetPacket)
        .filter(AssetPacket.thread_id == thread_id)
        .order_by(AssetPacket.id.desc())
        .all()
    )


def update_asset_packet(
    db: Session,
    packet: AssetPacket,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    packet_json: dict | None = None,
    reply_draft_id: object | None = ...,
) -> AssetPacket:
    if title is not None:
        packet.title = title
    if description is not None:
        packet.description = description
    if status is not None:
        packet.status = status
    if packet_json is not None:
        packet.packet_json = packet_json
    if reply_draft_id is not ...:
        packet.reply_draft_id = reply_draft_id  # type: ignore[assignment]

    db.add(packet)
    db.commit()
    db.refresh(packet)
    return packet


def delete_asset_packet(db: Session, packet_id: int) -> bool:
    row = db.query(AssetPacket).filter(AssetPacket.id == packet_id).first()
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def attach_packet_to_reply_draft(
    db: Session,
    packet_id: int,
    reply_draft_id: int,
) -> AssetPacket:
    packet = db.query(AssetPacket).filter(AssetPacket.id == packet_id).first()
    if not packet:
        raise ValueError("AssetPacket not found")

    reply = db.query(ReplyDraft).filter(ReplyDraft.id == reply_draft_id).first()
    if not reply:
        raise ValueError("ReplyDraft not found")

    if packet.run_id != reply.run_id:
        raise ValueError("run_id mismatch")

    if packet.thread_id is not None and packet.thread_id != reply.thread_id:
        raise ValueError("thread_id mismatch")

    if packet.status == "archived":
        raise ValueError("Archived packet cannot be attached")

    if packet.status == "sent":
        raise ValueError("Sent packet cannot be attached")

    existing_packets = (
        db.query(AssetPacket)
        .filter(AssetPacket.reply_draft_id == reply_draft_id)
        .all()
    )

    for existing in existing_packets:
        if existing.id != packet_id:
            raise ValueError("Reply draft already has a packet attached")

    packet.reply_draft_id = reply_draft_id

    db.add(packet)
    db.commit()
    db.refresh(packet)

    return packet
