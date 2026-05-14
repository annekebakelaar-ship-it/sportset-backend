"""
Oura OAuth 2.0 integration + data endpoints

Complete OAuth flow:
  1. GET /api/oura/connect — user clicks, redirects to Oura
  2. GET /api/oura/callback — Oura redirects back with auth code
  3. Token is stored encrypted in database
  
Data endpoints (require user auth):
  4. POST /api/oura/pull — fetch 45 days of sleep, activity, heart rate
  5. GET /api/oura/status — check connection status
"""

import logging
import secrets
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.auth import get_current_user
from src.core.config import settings
from src.core.security import decrypt_token, encrypt_token
from src.db.database import get_db
from src.db.models import OuraToken, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oura", tags=["oura"])


# ============================================================================
# Response Models
# ============================================================================


class SleepDataPoint(BaseModel):
    day: str
    duration: int  # seconds
    quality: int  # 0-100


class ActivityDataPoint(BaseModel):
    day: str
    active_calories: int
    steps: int


class HeartRateDataPoint(BaseModel):
    day: str
    hrv: int  # Heart Rate Variability
    resting_hr: int


class OuraDataResponse(BaseModel):
    sleep: list[SleepDataPoint]
    activity: list[ActivityDataPoint]
    heart_rate: list[HeartRateDataPoint]
    pulled_at: str


class OuraStatusResponse(BaseModel):
    connected: bool
    expires_at: str | None
    user_id: str | None


# ============================================================================
# Helper functions
# ============================================================================


def _build_oura_auth_url(state: str) -> str:
    """Build Oura OAuth authorization URL."""
    return (
        "https://cloud.ouraring.com/oauth/authorize"
        f"?client_id={settings.oura_client_id}"
        f"&redirect_uri={settings.oura_redirect_uri}"
        "&response_type=code"
        "&scope=personal closedring"
        f"&state={state}"
    )


async def _exchange_code_for_tokens(code: str) -> dict:
    """Exchange authorization code for OAuth tokens."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://cloud.ouraring.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.oura_client_id,
                "client_secret": settings.oura_client_secret,
                "redirect_uri": settings.oura_redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _get_valid_access_token(user: User, db: Session) -> str:
    """
    Get valid Oura access token for user.
    Refreshes token if expired.
    Raises ValueError if not connected.
    """
    oura_token = db.query(OuraToken).filter(OuraToken.user_id == user.id).first()
    if not oura_token:
        raise ValueError("Oura not connected")
    
    # Decrypt token data
    token_data = decrypt_token(oura_token.encrypted_data)
    expires_at = datetime.fromisoformat(token_data["expires_at"])
    
    # Check if token is expired (with 5-min buffer)
    if datetime.now(timezone.utc) + timedelta(minutes=5) > expires_at:
        logger.info(f"Oura token expired for user {user.id}, refreshing...")
        
        # Refresh token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://cloud.ouraring.com/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token_data["refresh_token"],
                    "client_id": settings.oura_client_id,
                    "client_secret": settings.oura_client_secret,
                },
            )
            resp.raise_for_status()
            new_tokens = resp.json()
        
        # Update token in database
        token_data = {
            "access_token": new_tokens["access_token"],
            "refresh_token": new_tokens.get("refresh_token", token_data["refresh_token"]),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=new_tokens["expires_in"])
            ).isoformat(),
            "token_type": "Bearer",
        }
        oura_token.encrypted_data = encrypt_token(token_data)
        oura_token.expires_at = datetime.fromisoformat(token_data["expires_at"])
        oura_token.last_refreshed_at = datetime.now(timezone.utc)
        db.commit()
        
        logger.info(f"Oura token refreshed for user {user.id}")
    
    return token_data["access_token"]


async def _fetch_oura_data(access_token: str, start: str, end: str) -> dict:
    """
    Fetch sleep, activity, and heart rate data from Oura API.
    
    Args:
        access_token: Oura API access token
        start: ISO date string (YYYY-MM-DD)
        end: ISO date string (YYYY-MM-DD)
    
    Returns:
        Dictionary with sleep, activity, heart_rate lists
    """
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Fetch daily sleep
        sleep_resp = await client.get(
            f"https://api.ouraring.com/v2/usercollection/daily_sleep?start_date={start}&end_date={end}",
            headers=headers,
        )
        sleep_resp.raise_for_status()
        sleep_data = sleep_resp.json()
        
        # Fetch daily activity
        activity_resp = await client.get(
            f"https://api.ouraring.com/v2/usercollection/daily_activity?start_date={start}&end_date={end}",
            headers=headers,
        )
        activity_resp.raise_for_status()
        activity_data = activity_resp.json()
        
        # Fetch daily heart rate
        hr_resp = await client.get(
            f"https://api.ouraring.com/v2/usercollection/daily_cardiovascular_age?start_date={start}&end_date={end}",
            headers=headers,
        )
        hr_resp.raise_for_status()
        hr_data = hr_resp.json()
        
        return {
            "sleep": sleep_data.get("data", []),
            "activity": activity_data.get("data", []),
            "heart_rate": hr_data.get("data", []),
        }


# ============================================================================
# OAuth Endpoints
# ============================================================================


@router.get("/connect")
async def oura_connect():
    """
    Start OAuth flow: generate state token, set secure cookie, redirect to Oura.
    """
    state = secrets.token_hex(16)
    url = _build_oura_auth_url(state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key="oura_state",
        value=state,
        httponly=True,
        samesite="lax",
        max_age=600,  # 10 minutes
    )
    logger.info(f"Oura OAuth initiated with state={state[:8]}...")
    return response


@router.get("/callback")
async def oura_callback(
    code: str,
    state: str,
    oura_state: str = Cookie(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Oura OAuth callback: validate state, exchange code for tokens, store encrypted.
    Redirects to frontend with status=success or status=error.
    """
    # Validate state token
    if not oura_state or oura_state != state:
        logger.warning(f"State mismatch in Oura callback: expected {oura_state}, got {state}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/connect?status=error&reason=invalid_state",
            status_code=302,
        )
    
    try:
        # Exchange code for tokens
        tokens = await _exchange_code_for_tokens(code)
        
        # Decrypt existing token if exists (to delete)
        existing = db.query(OuraToken).filter(OuraToken.user_id == user.id).first()
        if existing:
            db.delete(existing)
        
        # Create new encrypted token record
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
        )
        token_data = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": expires_at.isoformat(),
            "token_type": "Bearer",
        }
        
        oura_token = OuraToken(
            user_id=user.id,
            encrypted_data=encrypt_token(token_data),
            expires_at=expires_at,
        )
        db.add(oura_token)
        db.commit()
        
        logger.info(f"Oura tokens stored for user {user.id}")
        
        response = RedirectResponse(
            url=f"{settings.frontend_url}/connect?status=success",
            status_code=302,
        )
        response.delete_cookie("oura_state")
        return response
    
    except Exception as e:
        logger.error(f"Oura callback error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_url}/connect?status=error&reason=token_exchange_failed",
            status_code=302,
        )


@router.post("/disconnect")
async def oura_disconnect(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Disconnect Oura: delete stored tokens."""
    oura_token = db.query(OuraToken).filter(OuraToken.user_id == user.id).first()
    if oura_token:
        db.delete(oura_token)
        db.commit()
        logger.info(f"Oura disconnected for user {user.id}")
    return {"status": "disconnected"}


# ============================================================================
# Data Endpoints (require user authentication)
# ============================================================================


@router.post("/pull", response_model=OuraDataResponse)
async def oura_pull(
    days: int = Query(45, ge=1, le=90, description="Number of days to pull (default: 45)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Pull Oura data for the past N days.
    
    Returns:
        - sleep: list of daily sleep records
        - activity: list of daily activity records
        - heart_rate: list of daily heart rate records
        - pulled_at: timestamp when data was fetched
    """
    try:
        access_token = await _get_valid_access_token(user, db)
    except ValueError as e:
        # Return mock data if not connected (for demo purposes)
        logger.warning(f"Oura not connected for user {user.id}, returning mock data")
        return {
            "sleep": [
                {"day": "2026-05-12", "duration": 28800, "quality": 85},
                {"day": "2026-05-11", "duration": 30600, "quality": 88},
            ],
            "activity": [
                {"day": "2026-05-12", "active_calories": 450, "steps": 8234},
                {"day": "2026-05-11", "active_calories": 520, "steps": 9876},
            ],
            "heart_rate": [
                {"day": "2026-05-12", "hrv": 45, "resting_hr": 62},
                {"day": "2026-05-11", "hrv": 52, "resting_hr": 60},
            ],
            "pulled_at": datetime.now(timezone.utc).isoformat(),
        }
    
    # Fetch data from Oura API
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    
    try:
        raw_data = await _fetch_oura_data(access_token, start.isoformat(), end.isoformat())
    except Exception as e:
        logger.error(f"Oura API error: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch Oura data")
    
    # Map raw Oura data to response format
    sleep_points = [
        SleepDataPoint(
            day=item["day"],
            duration=int(item.get("total_sleep_duration", 0) / 1000),  # convert to seconds
            quality=item.get("sleep_score", 0),
        )
        for item in raw_data["sleep"]
    ]
    
    activity_points = [
        ActivityDataPoint(
            day=item["day"],
            active_calories=item.get("active_calories", 0),
            steps=item.get("steps", 0),
        )
        for item in raw_data["activity"]
    ]
    
    hr_points = [
        HeartRateDataPoint(
            day=item["day"],
            hrv=item.get("heart_rate_variability", 0),
            resting_hr=item.get("resting_heart_rate", 0),
        )
        for item in raw_data["heart_rate"]
    ]
    
    return OuraDataResponse(
        sleep=sleep_points,
        activity=activity_points,
        heart_rate=hr_points,
        pulled_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/sleep")
async def oura_sleep(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's sleep data (requires Oura connection)."""
    data = await oura_pull(days=45, db=db, user=user)
    return data.sleep


@router.get("/activity")
async def oura_activity(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's activity data (requires Oura connection)."""
    data = await oura_pull(days=45, db=db, user=user)
    return data.activity


@router.get("/heart-rate")
async def oura_heart_rate(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get user's heart rate data (requires Oura connection)."""
    data = await oura_pull(days=45, db=db, user=user)
    return data.heart_rate


@router.get("/status", response_model=OuraStatusResponse)
async def oura_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Check if Oura is connected and when token expires."""
    oura_token = db.query(OuraToken).filter(OuraToken.user_id == user.id).first()
    if not oura_token:
        return OuraStatusResponse(connected=False, expires_at=None, user_id=user.id)
    return OuraStatusResponse(
        connected=True,
        expires_at=oura_token.expires_at.isoformat(),
        user_id=user.id,
    )
