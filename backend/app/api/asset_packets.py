from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.asset_packet_repo import (
    attach_packet_to_reply_draft,
    get_asset_packet,
    list_asset_packets_by_run,
    list_asset_packets_by_thread,
    update_asset_packet,
)
from app.schemas.asset_packet import (
    AssetPacketRead,
    AssetPacketUpdate,
    AttachReplyDraftRequest,
    UpdateAssetPacketAssetsRequest,
)
from app.services.asset_packet_service import (
    build_asset_packet_for_thread,
    clone_asset_packet,
    update_packet_assets,
)

router = APIRouter(prefix="/asset-packets", tags=["asset-packets"])


@router.get("/run/{run_id}", response_model=list[AssetPacketRead])
def list_asset_packets_for_run(run_id: int, db: Session = Depends(get_db)):
    return list_asset_packets_by_run(db, run_id)


@router.get("/thread/{thread_id}", response_model=list[AssetPacketRead])
def list_asset_packets_for_thread_route(thread_id: int, db: Session = Depends(get_db)):
    return list_asset_packets_by_thread(db, thread_id)


@router.post("/thread/{thread_id}/build")
def build_asset_packet_route(thread_id: int, db: Session = Depends(get_db)):
    try:
        return build_asset_packet_for_thread(db, thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{packet_id}", response_model=AssetPacketRead)
def update_asset_packet_route(
    packet_id: int,
    payload: AssetPacketUpdate,
    db: Session = Depends(get_db),
):
    packet = get_asset_packet(db, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Asset packet not found")

    if packet.status == "sent":
        mutates = (
            payload.title is not None
            or payload.description is not None
            or payload.packet_json is not None
        )
        archiving_only = payload.status == "archived"
        if mutates or (payload.status is not None and not archiving_only):
            raise HTTPException(
                status_code=400,
                detail="Sent packet is locked; only archiving is allowed",
            )

    return update_asset_packet(
        db=db,
        packet=packet,
        title=payload.title,
        description=payload.description,
        status=payload.status,
        packet_json=payload.packet_json,
    )


@router.get("/{packet_id}", response_model=AssetPacketRead)
def get_asset_packet_route(packet_id: int, db: Session = Depends(get_db)):
    packet = get_asset_packet(db, packet_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Asset packet not found")
    return packet


@router.patch("/{packet_id}/assets", response_model=AssetPacketRead)
def update_asset_packet_assets_route(
    packet_id: int,
    payload: UpdateAssetPacketAssetsRequest,
    db: Session = Depends(get_db),
):
    try:
        return update_packet_assets(
            db=db,
            packet_id=packet_id,
            assets_payload=[item.model_dump() for item in payload.assets],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{packet_id}/clone", response_model=AssetPacketRead)
def clone_asset_packet_route(packet_id: int, db: Session = Depends(get_db)):
    try:
        return clone_asset_packet(db=db, packet_id=packet_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{packet_id}/attach-reply-draft", response_model=AssetPacketRead)
def attach_packet_to_reply_draft_route(
    packet_id: int,
    payload: AttachReplyDraftRequest,
    db: Session = Depends(get_db),
):
    try:
        return attach_packet_to_reply_draft(
            db,
            packet_id=packet_id,
            reply_draft_id=payload.reply_draft_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
