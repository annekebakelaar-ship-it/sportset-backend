"""
Oura OAuth client and API calls.
All HTTP via httpx (already in requirements).
# PRIVACY: raw biometric data is never persisted by this module.
"""
import asyncio
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
_API_BASE = "https://api.ouraring.com/v2/usercollection"
SCOPES = "daily heartrate workout personal email"


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_tokens(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_daily_data(
    access_token: str,
    start: str,
    end: str,
) -> dict:
    """
    Pull readiness, sleep, activity, temperature in parallel.
    Date format: YYYY-MM-DD.
    Missing endpoints return {"data": []} so the mapper never crashes.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"start_date": start, "end_date": end}
    endpoints = {
        "readiness": f"{_API_BASE}/daily_readiness",
        "sleep":     f"{_API_BASE}/sleep",
        "activity":  f"{_API_BASE}/daily_activity",
        "temperature": f"{_API_BASE}/temperature",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        responses = await asyncio.gather(
            *[client.get(url, params=params, headers=headers) for url in endpoints.values()],
            return_exceptions=True,
        )

    result: dict[str, dict] = {}
    for key, resp in zip(endpoints.keys(), responses):
        if isinstance(resp, Exception):
            result[key] = {"data": []}
        else:
            try:
                resp.raise_for_status()
                result[key] = resp.json()
            except Exception:
                result[key] = {"data": []}
    return result
