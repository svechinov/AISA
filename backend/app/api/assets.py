from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.asset_repo import create_asset, list_assets
from app.schemas.asset import AssetCreate, AssetRead, build_asset_read
from app.services.cdn_upload_service import upload_bytes_to_project_cdn, upload_max_bytes

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets_route(db: Session = Depends(get_db)):
    rows = list_assets(db, status=None)
    return [build_asset_read(db, a) for a in rows]


@router.post("/upload", response_model=AssetRead)
def upload_asset_route(
    file: UploadFile = File(...),
    name: str = Form(...),
    asset_type: str = Form("other"),
    db: Session = Depends(get_db),
):
    raw_name = (name or "").strip()
    if not raw_name:
        raise HTTPException(status_code=422, detail="Name is required.")
    max_b = upload_max_bytes()
    data = file.file.read(max_b + 1)
    if len(data) > max_b:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {max_b // (1024 * 1024)} MB).",
        )
    orig = (file.filename or "upload").strip() or "upload"
    ct = (file.content_type or "").strip() or None
    try:
        meta = upload_bytes_to_project_cdn(data, original_filename=orig, content_type=ct)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    a = create_asset(
        db=db,
        asset_type=(asset_type or "other").strip() or "other",
        name=raw_name,
        description=None,
        url=meta["url"],
        file_path=None,
        download_url=meta["url"],
        storage_key=meta.get("storage_key"),
        filename=meta.get("filename"),
        mime_type=meta.get("mime_type"),
        file_size_bytes=meta.get("file_size_bytes"),
        status="active",
        metadata_json=meta.get("metadata_json") or {},
    )
    return build_asset_read(db, a)


@router.post("", response_model=AssetRead)
def create_asset_route(payload: AssetCreate, db: Session = Depends(get_db)):
    a = create_asset(
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
    return build_asset_read(db, a)
