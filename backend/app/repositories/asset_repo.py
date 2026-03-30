from sqlalchemy.orm import Session

from app.models.asset import Asset


def create_asset(
    db: Session,
    asset_type: str,
    name: str,
    description: str | None = None,
    url: str | None = None,
    file_path: str | None = None,
    download_url: str | None = None,
    storage_key: str | None = None,
    filename: str | None = None,
    mime_type: str | None = None,
    file_size_bytes: int | None = None,
    status: str = "active",
    metadata_json: dict | None = None,
) -> Asset:
    asset = Asset(
        asset_type=asset_type,
        name=name,
        description=description,
        url=url,
        file_path=file_path,
        download_url=download_url,
        storage_key=storage_key,
        filename=filename,
        mime_type=mime_type,
        file_size_bytes=file_size_bytes,
        status=status,
        metadata_json=metadata_json or {},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def get_asset(db: Session, asset_id: int) -> Asset | None:
    return db.query(Asset).filter(Asset.id == asset_id).first()


def list_assets(db: Session, status: str | None = "active") -> list[Asset]:
    query = db.query(Asset)
    if status is not None:
        query = query.filter(Asset.status == status)
    return query.order_by(Asset.id.asc()).all()
