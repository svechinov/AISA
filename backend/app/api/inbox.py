from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.inbox import MockReplyCreate
from app.services.inbox_service import receive_mock_reply

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.post("/mock-receive")
def mock_receive_route(payload: MockReplyCreate, db: Session = Depends(get_db)):
    try:
        return receive_mock_reply(
            db=db,
            draft_id=payload.draft_id,
            from_email=payload.from_email,
            to_email=payload.to_email,
            subject=payload.subject,
            body=payload.body,
            provider_message_id=payload.provider_message_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
