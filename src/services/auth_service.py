"""
Authentication Service — Magic Link & JWT
"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

from jose import JWTError, jwt
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, Header

from backend.core.config import settings
from backend.db.database import get_db
from backend.models.orm_models import UserORM, MagicLinkTokenORM
from backend.services.email_service import send_magic_link


# Config
APP_SECRET_KEY = settings.app_secret_key
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = int(os.getenv("JWT_TTL_DAYS", "30"))
MAGIC_LINK_TTL_MINUTES = int(os.getenv("MAGIC_LINK_TTL_MINUTES", "15"))
APP_URL = os.getenv("APP_URL", "http://localhost:5500")


async def request_magic_link(db: Session, email: str) -> None:
    """Generate and send magic link"""
    # Generate token
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Get or create user
    user = db.query(UserORM).filter(UserORM.email == email).first()
    user_id = user.id if user else None
    
    # Save token
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
    magic_link = MagicLinkTokenORM(
        token_hash=token_hash,
        email=email,
        user_id=user_id,
        expires_at=expires_at,
    )
    db.add(magic_link)
    db.commit()
    
    # Send email — link_url bevat het token als query-param
    link_url = f"{APP_URL}/auth/verify?token={token}"
    send_magic_link(email, link_url)


async def verify_magic_link(db: Session, token: str) -> Tuple[Optional[UserORM], Optional[str]]:
    """Verify token and return user + JWT"""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Find token
    magic_link = db.query(MagicLinkTokenORM).filter(
        MagicLinkTokenORM.token_hash == token_hash
    ).first()
    
    if not magic_link or magic_link.consumed_at:
        return None, None
    
    if datetime.now(timezone.utc) > magic_link.expires_at:
        return None, None
    
    # Get or create user
    user = db.query(UserORM).filter(UserORM.email == magic_link.email).first()
    if not user:
        user = UserORM(email=magic_link.email, is_active=True)
        db.add(user)
        db.flush()
    
    # Mark token as consumed
    magic_link.consumed_at = datetime.now(timezone.utc)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    
    # Generate JWT
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_TTL_DAYS),
    }
    jwt_token = jwt.encode(payload, APP_SECRET_KEY, algorithm=JWT_ALGORITHM)
    
    return user, jwt_token


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> UserORM:
    """Dependency to get current authenticated user"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        scheme, token = authorization.split(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    try:
        payload = jwt.decode(token, APP_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(UserORM).filter(UserORM.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user
