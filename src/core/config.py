"""
backend/core/config.py
----------------------
Centrale configuratie voor YouCaps via pydantic-settings.
Laadt automatisch uit omgevingsvariabelen of het .env bestand.

Gebruik:
    from src.core.config import settings
    print(settings.anthropic_api_key)
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Applicatie-brede instellingen geladen uit omgevingsvariabelen / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Anthropic ---
    anthropic_api_key: str | None = Field(
        None,
        description="Anthropic Claude API-sleutel (verplicht in productie; None geeft fout bij eerste AI-aanroep)",
    )

    # --- Applicatie ---
    app_env: str = Field("development", description="development | staging | production")
    app_secret_key: str = Field(
        "insecure-dev-secret-change-in-production",
        description="Willekeurige geheime sleutel voor JWT-signing (64+ tekens in productie)",
    )
    debug: bool = Field(True, description="Schakel debug-modus in of uit")
    app_version: str = Field("0.3.0", description="Applicatieversie")

    # --- Database ---
    database_url: str = Field(
        "sqlite:///./backend/db/youcaps.db",
        description="SQLAlchemy database-URL",
    )

    # --- CORS ---
    # NB: type is `str | List[str]` zodat pydantic-settings de waarde NIET
    # automatisch als JSON probeert te parsen (oude gedrag faalde op
    # `ALLOWED_ORIGINS=http://...,http://...`). De ``_split_origins``
    # validator hieronder zet een komma-gescheiden string om naar een lijst.
    allowed_origins: str | List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:8000",
        ],
        description="Toegestane frontend-origins voor CORS (exact match)",
    )

    allowed_origin_regex: str | None = Field(
        # Default: sta alle VS Code Dev Tunnels en ngrok hosts toe.
        # Hierdoor kan een telefoon via de tunnel-URL de API aanroepen
        # zonder dat je voor elke nieuwe tunnel-id de .env hoeft bij te
        # werken. In productie kun je dit op None zetten.
        default=r"https://.*\.devtunnels\.ms|https://.*\.ngrok-free\.app|https://.*\.ngrok\.io|https://.*\.trycloudflare\.com",
        description=(
            "Regex voor extra toegestane CORS-origins. Handig voor "
            "VS Code devtunnels / ngrok URLs die per sessie veranderen."
        ),
    )

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """
        Sta zowel een lijst als een komma-gescheiden string toe (uit .env).

        Accepteert ook het oudere JSON-array formaat
        (``ALLOWED_ORIGINS=["http://a","http://b"]``) zodat we
        bestaande .env-bestanden niet breken.
        """
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("[") and s.endswith("]"):
                import json as _json
                try:
                    parsed = _json.loads(s)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except _json.JSONDecodeError:
                    pass  # val terug op komma-split
            return [item.strip() for item in s.split(",") if item.strip()]
        return v

    @field_validator("allowed_origin_regex", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        """Lege string in .env => None (regex uit)."""
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        # Vroeg-valideren zodat een verkeerde regex hard faalt bij startup.
        if isinstance(v, str):
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"Ongeldige ALLOWED_ORIGIN_REGEX: {exc}") from exc
        return v

    # --- Rate limiting ---
    rate_limit_ai_calls: str = Field(
        "10/minute",
        description="Max AI-aanroepen (legacy text-scan) per gebruiker per minuut",
    )
    rate_limit_scan: str = Field(
        "10/minute",
        description="Max foto-scans per IP per minuut",
    )
    rate_limit_global: str = Field(
        "60/minute",
        description="Globale fallback per IP",
    )

    # --- Knowledge Base ---
    knowledge_base_path: str = Field(
        "backend/db/knowledge_base.json",
        description="Pad naar de knowledge base JSON (relatief aan project-root)",
    )

    # --- Vision Scanner (Fase 3) ---
    # NB: HARD-FORCED naar 20240620. Negeert evt. afwijkende waarde uit .env
    # om te voorkomen dat een verouderde model-id (bijv. 20241022) blijft
    # hangen vanuit een achtergebleven proces of cache.
    vision_model: str = Field(
        "claude-haiku-4-5-20251001",
        description="Anthropic vision-capable model-id (geforceerd)",
    )

    @field_validator("vision_model", mode="before")
    @classmethod
    def _force_vision_model(cls, v):
        """Forceer altijd het werkende model — onafhankelijk van .env-waarde."""
        forced = "claude-haiku-4-5-20251001"
        if v and v != forced:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "VISION_MODEL='%s' uit env genegeerd; geforceerd naar '%s'.",
                v,
                forced,
            )
        return forced

    vision_max_tokens: int = Field(1500, ge=256, le=8192)
    vision_temperature: float = Field(0.0, ge=0.0, le=1.0)
    vision_timeout_seconds: float = Field(30.0, gt=0)
    vision_max_retries: int = Field(3, ge=0, le=6)

    # --- Image Upload ---
    max_upload_mb: int = Field(10, ge=1, le=50, description="Hard upload-limit in MB")
    image_max_dimension: int = Field(1568, ge=512, le=4096)
    image_min_dimension: int = Field(200, ge=50, le=1024)

    # --- Matching engine ---
    match_strong_threshold: float = Field(0.85, ge=0.0, le=1.0)
    match_weak_threshold: float = Field(0.65, ge=0.0, le=1.0)

    # --- Oura OAuth (Fase 4) ---
    oura_client_id: str = Field("", description="Oura Cloud OAuth client ID")
    oura_client_secret: str = Field("", description="Oura Cloud OAuth client secret")
    oura_redirect_uri: str = Field(
        "http://localhost:8000/api/oura/callback",
        description="Oura OAuth redirect URI — must match Oura developer console exactly",
    )

    # --- Supabase (Fase 4) ---
    supabase_url: str = Field("", description="Supabase project URL")
    supabase_service_role_key: str = Field(
        "", description="Supabase service role key (server-side only, never expose to browser)"
    )

    # --- Token Encryption (Fase 4) ---
    token_encryption_key: str = Field(
        "", description="AES-256-GCM key: 64 hex chars (32 bytes). Generate: openssl rand -hex 32"
    )

    # --- Frontend (Fase 4) ---
    frontend_url: str = Field(
        "http://localhost:5173",
        description="Frontend base URL — used for post-OAuth redirect",
    )

    # --- Berekende properties ---
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retourneert gecachede Settings-instantie.
    Gebruik get_settings() als FastAPI dependency of in module-level code.
    """
    return Settings()


# Gemaks-alias — gebruik `settings` in de rest van de codebase
settings = get_settings()
