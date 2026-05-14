"""
User authentication endpoints: register, login, logout, current_user
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.security import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from src.db.database import get_db
from src.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ============================================================================
# Request/Response Models
# ============================================================================


class RegisterRequest(BaseModel):
    """Register new user with email and password."""
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    """Login with email and password."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Access token response."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User profile response."""
    id: str
    email: str
    name: str | None
    subscription_status: str
    is_active: bool
    
    class Config:
        from_attributes = True


class CurrentUserResponse(UserResponse):
    """Extended user info for /auth/me endpoint."""
    pass


# ============================================================================
# Dependency: Get current authenticated user
# ============================================================================


async def get_current_user(
    authorization: str | None = None,
    db: Session = Depends(get_db),
) -> User:
    """
    Extract and validate JWT token from Authorization header.
    Returns the User object or raises HTTPException 401.
    
    Usage:
        @app.get("/protected")
        async def protected(user: User = Depends(get_current_user)):
            return {"user_id": user.id}
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = parts[1]
    
    try:
        payload = verify_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    
    return user


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    req: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Register new user account.
    Returns JWT access token on success.
    """
    # Check if email already exists
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    
    # Hash password and create user
    hashed_pwd = hash_password(req.password)
    user = User(
        email=req.email,
        name=req.name,
        hashed_password=hashed_pwd,
        subscription_status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    logger.info(f"User registered: {user.email} (id={user.id})")
    
    # Generate JWT token
    token = create_access_token(user.id, user.email)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login", response_model=TokenResponse)
def login(
    req: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    Login with email and password.
    Returns JWT access token on success.
    """
    user = db.query(User).filter(User.email == req.email).first()
    
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )
    
    logger.info(f"User logged in: {user.email}")
    
    # Generate JWT token
    token = create_access_token(user.id, user.email)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user_info(
    user: User = Depends(get_current_user),
):
    """
    Get current authenticated user profile.
    Requires valid JWT token in Authorization header.
    """
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: User = Depends(get_current_user)):
    """
    Logout user (JWT is invalidated on client side).
    In a production app, you might want to maintain a token blacklist.
    """
    logger.info(f"User logged out: {user.email}")
    return None
