from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    token: str

@router.post("/login")
def login(req: LoginRequest):
    if not settings.GLOBAL_PASSWORD:
        return LoginResponse(token="no-auth-required")
    
    if req.password == settings.GLOBAL_PASSWORD:
        return LoginResponse(token=req.password)
    
    raise HTTPException(status_code=401, detail="Invalid password")
