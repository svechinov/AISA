from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.asset_repo import create_asset, list_assets
from app.schemas.asset import AssetCreate, AssetRead

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets_route(db: Session = Depends(get_db)):
    return list_assets(db, status=None)


@router.post("", response_model=AssetRead)
def create_asset_route(payload: AssetCreate, db: Session = Depends(get_db)):
    return create_asset(
        db=db,
        asset_type=payload.asset_type,
        name=payload.name,
        description=payload.description,
        url=payload.url,
        file_path=payload.file_path,
        download_url=payload.download_url,
        storage_key=payload.storage_key,
        filename=payload.filename,
        mime_type=payload.mime_type,
        file_size_bytes=payload.file_size_bytes,
        status=payload.status,
        metadata_json=payload.metadata_json,
    )
