"""
Authentication API — Magic Link Flow
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.database import get_db
from src.services.auth_service import (
    request_magic_link, verify_magic_link, get_current_user,
    APP_SECRET_KEY, JWT_ALGORITHM, JWT_TTL_DAYS,
)
from src.models.orm_models import UserORM


router = APIRouter(prefix="/auth", tags=["auth"])


# Request Models
class RequestMagicLinkRequest(BaseModel):
    email: EmailStr


class VerifyMagicLinkRequest(BaseModel):
    token: str


# Response Models
class MeResponse(BaseModel):
    id: str
    email: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# Endpoints
@router.post("/request-link", status_code=204)
async def request_link(
    req: RequestMagicLinkRequest,
    db: Session = Depends(get_db),
):
    """Request magic link for email"""
    await request_magic_link(db, req.email)


@router.post("/verify", response_model=TokenResponse)
async def verify_link(
    req: VerifyMagicLinkRequest,
    db: Session = Depends(get_db),
):
    """Verify magic link and get JWT"""
    user, token = await verify_magic_link(db, req.token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: UserORM = Depends(get_current_user),
):
    """Get current user info"""
    return user


@router.get("/dev-token", response_model=TokenResponse)
def dev_token(db: Session = Depends(get_db)):
    """Dev-only: geeft JWT terug voor dev@youcaps.ai — niet beschikbaar in productie."""
    if not settings.is_development:
        raise HTTPException(status_code=404, detail="Not found")

    from datetime import datetime, timedelta, timezone
    from jose import jwt as _jwt

    user = db.query(UserORM).filter(UserORM.email == "dev@youcaps.ai").first()
    if not user:
        user = UserORM(email="dev@youcaps.ai", is_active=True, hashed_password="dev-placeholder")
        db.add(user)
        db.commit()
        db.refresh(user)

    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_TTL_DAYS),
    }
    token = _jwt.encode(payload, APP_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}
