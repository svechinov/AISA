from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import datetime

from app.db import get_db
from app.models.smtp_account import SmtpAccount

router = APIRouter(prefix="/smtp-accounts", tags=["smtp-accounts"])

class SmtpAccountCreate(BaseModel):
    email: str
    password: str
    smtp_server: str = "smtp.yandex.ru"
    smtp_port: int = 465
    imap_server: str = "imap.yandex.ru"
    imap_port: int = 993
    daily_limit: int = 50
    is_active: bool = True

class SmtpAccountResponse(SmtpAccountCreate):
    id: int
    sent_today: int
    last_used_at: Optional[datetime.datetime] = None
    reset_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True

@router.get("/", response_model=List[SmtpAccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    return db.query(SmtpAccount).all()

@router.post("/", response_model=SmtpAccountResponse)
def create_account(account: SmtpAccountCreate, db: Session = Depends(get_db)):
    existing = db.query(SmtpAccount).filter(SmtpAccount.email == account.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Account with this email already exists")
    
    db_acc = SmtpAccount(**account.model_dump())
    db.add(db_acc)
    db.commit()
    db.refresh(db_acc)
    return db_acc

@router.delete("/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    db_acc = db.query(SmtpAccount).filter(SmtpAccount.id == account_id).first()
    if not db_acc:
        raise HTTPException(status_code=404, detail="Account not found")
    
    db.delete(db_acc)
    db.commit()
    return {"status": "deleted"}
