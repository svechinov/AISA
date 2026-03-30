from sqlalchemy.orm import Session

from app.models.email_attachment import EmailAttachment


def create_email_attachment(
    db: Session,
    message_id: int,
    filename: str,
    mime_type: str,
    asset_id: int | None = None,
    source_url: str | None = None,
    source_path: str | None = None,
    provider_attachment_id: str | None = None,
    status: str = "attached",
    error: str | None = None,
) -> EmailAttachment:
    row = EmailAttachment(
        message_id=message_id,
        asset_id=asset_id,
        filename=filename,
        mime_type=mime_type,
        source_url=source_url,
        source_path=source_path,
        provider_attachment_id=provider_attachment_id,
        status=status,
        error=error,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_many_email_attachments(db: Session, rows: list[dict]) -> list[EmailAttachment]:
    out: list[EmailAttachment] = []
    for r in rows:
        row = EmailAttachment(
            message_id=r["message_id"],
            asset_id=r.get("asset_id"),
            filename=r["filename"],
            mime_type=r["mime_type"],
            source_url=r.get("source_url"),
            source_path=r.get("source_path"),
            provider_attachment_id=r.get("provider_attachment_id"),
            status=r.get("status", "attached"),
            error=r.get("error"),
        )
        db.add(row)
        out.append(row)
    db.commit()
    for row in out:
        db.refresh(row)
    return out
