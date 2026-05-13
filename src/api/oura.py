"""
Oura OAuth + data API routes.

MVP assumption: single test user (user_id = "test-user").
# PENDING_PRODUCTION_HARDENING: tie user_id to auth session, add rate limiting,
# add error monitoring, add GDPR delete endpoint.
"""
import secrets
from datetime import date, timedelta, datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import RedirectResponse

from src.core.config import settings
from src.schemas.oura import OuraPullResponse, OuraStatusResponse
from src.services.oura.client import (
    build_auth_url,
    exchange_code_for_tokens,
    fetch_daily_data,
)
from src.services.oura.mapper import map_oura_to_daily_data_points
from src.services.oura.storage import (
    get_connection_status,
    get_valid_access_token,
    save_tokens,
)

TEST_USER_ID = "test-user"

router = APIRouter(prefix="/api/oura", tags=["oura"])


@router.get("/connect")
async def oura_connect():
    """Start OAuth: generate state, set cookie, redirect to Oura."""
    state = secrets.token_hex(16)
    url = build_auth_url(settings.oura_client_id, settings.oura_redirect_uri, state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key="oura_state",
        value=state,
        httponly=True,
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/callback")
async def oura_callback(
    code: str,
    state: str,
    oura_state: str = Cookie(default=None),
):
    """Receive authorization code, exchange for tokens, store, redirect to UI."""
    if not oura_state or oura_state != state:
        raise HTTPException(status_code=400, detail="invalid_state")

    tokens = await exchange_code_for_tokens(
        code=code,
        client_id=settings.oura_client_id,
        client_secret=settings.oura_client_secret,
        redirect_uri=settings.oura_redirect_uri,
    )
    await save_tokens(TEST_USER_ID, tokens)

    response = RedirectResponse(
        url=f"{settings.frontend_url}/connect?status=success",
        status_code=302,
    )
    response.delete_cookie("oura_state")
    return response


@router.post("/pull")
async def oura_pull():
    """
    Pull 45 days of Oura data ending yesterday.
    Returns DailyDataPoint[] — raw data is NOT persisted server-side.
    # PRIVACY: biometric data lives only in the browser's sessionStorage.
    """
    try:
        access_token = await get_valid_access_token(TEST_USER_ID)
    except ValueError:
        # MVP: Return mock data if not connected
        mock_data = {
            "sleep": [
                {"day": "2026-05-12", "duration": 28800, "quality": 85},
                {"day": "2026-05-11", "duration": 30600, "quality": 88},
                {"day": "2026-05-10", "duration": 27000, "quality": 82},
            ],
            "activity": [
                {"day": "2026-05-12", "active_calories": 450, "steps": 8234},
                {"day": "2026-05-11", "active_calories": 520, "steps": 9876},
                {"day": "2026-05-10", "active_calories": 380, "steps": 6543},
            ],
            "heart_rate": [
                {"day": "2026-05-12", "hrv": 45, "resting_hr": 62},
                {"day": "2026-05-11", "hrv": 52, "resting_hr": 60},
                {"day": "2026-05-10", "hrv": 38, "resting_hr": 65},
            ],
        }
        return OuraPullResponse(
            data=mock_data,
            pulled_at=datetime.now(timezone.utc).isoformat(),
        )

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=44)

    raw = await fetch_daily_data(access_token, start.isoformat(), end.isoformat())
    points = map_oura_to_daily_data_points(raw, start.isoformat(), end.isoformat())

    return OuraPullResponse(
        data=points,
        pulled_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/status", response_model=OuraStatusResponse)
async def oura_status():
    """Return connection status for the test user."""
    status = await get_connection_status(TEST_USER_ID)
    return OuraStatusResponse(**status)
