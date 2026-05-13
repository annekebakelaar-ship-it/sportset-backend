"""
Supabase-backed token storage for Oura connections.

Design:
- Sync Supabase client runs in asyncio.to_thread so the FastAPI event loop stays unblocked.
- Async functions (refresh_tokens) are awaited directly in the async wrapper.
- Tokens are always encrypted before storage; never logged.
"""
import asyncio
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

from src.core.config import settings
from src.services.oura.encryption import encrypt, decrypt

_TABLE = "wearable_connections"


def _client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


# ── sync internals (called via asyncio.to_thread) ──────────────────────────

def _save_tokens_sync(user_id: str, token_response: dict) -> None:
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=token_response["expires_in"])
    ).isoformat()
    _client().table(_TABLE).upsert(
        {
            "user_id": user_id,
            "provider": "oura",
            "access_token_encrypted":  encrypt(token_response["access_token"]),
            "refresh_token_encrypted": encrypt(token_response["refresh_token"]),
            "expires_at": expires_at,
            "scope": token_response.get("scope", ""),
        },
        on_conflict="user_id,provider",
    ).execute()


def _get_row_sync(user_id: str) -> dict | None:
    result = (
        _client()
        .table(_TABLE)
        .select("access_token_encrypted,refresh_token_encrypted,expires_at")
        .eq("user_id", user_id)
        .eq("provider", "oura")
        .execute()
    )
    return result.data[0] if result.data else None


def _get_status_sync(user_id: str) -> dict | None:
    result = (
        _client()
        .table(_TABLE)
        .select("expires_at")
        .eq("user_id", user_id)
        .eq("provider", "oura")
        .execute()
    )
    return result.data[0] if result.data else None


# ── async public API ────────────────────────────────────────────────────────

async def save_tokens(user_id: str, token_response: dict) -> None:
    await asyncio.to_thread(_save_tokens_sync, user_id, token_response)


async def get_valid_access_token(user_id: str) -> str:
    """
    Returns a valid access token, refreshing automatically if <5 min remain.
    Raises ValueError("no_connection") when no row exists for this user.
    """
    row = await asyncio.to_thread(_get_row_sync, user_id)
    if not row:
        raise ValueError("no_connection")

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if (expires_at - datetime.now(timezone.utc)).total_seconds() < 300:
        from src.services.oura.client import refresh_tokens as _refresh
        new_tokens = await _refresh(
            decrypt(row["refresh_token_encrypted"]),
            settings.oura_client_id,
            settings.oura_client_secret,
        )
        await asyncio.to_thread(_save_tokens_sync, user_id, new_tokens)
        return new_tokens["access_token"]

    return decrypt(row["access_token_encrypted"])


async def get_connection_status(user_id: str) -> dict:
    row = await asyncio.to_thread(_get_status_sync, user_id)
    if not row:
        return {"connected": False}
    return {"connected": True, "expires_at": row["expires_at"]}
