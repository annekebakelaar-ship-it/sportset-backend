"""
backend/db/migrations/env.py
-----------------------------
Alembic omgevingsconfigurator voor YouCaps.

Leest DATABASE_URL uit omgevingsvariabelen (via backend.core.config),
zodat alembic.ini GEEN hardcoded credentials bevat.

Gebruik:
    alembic revision --autogenerate -m "beschrijving"
    alembic upgrade head
    alembic downgrade -1
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Voeg project-root toe aan sys.path zodat backend-imports werken
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# ---------------------------------------------------------------------------
# Alembic config-object — geeft toegang tot alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Laad logging-configuratie uit alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Importeer de Base en alle ORM-modellen
# (alle modellen MOETEN geïmporteerd zijn zodat Base.metadata ze kent)
# ---------------------------------------------------------------------------
from src.db.database import Base  # noqa: E402
from src.models import orm_models  # noqa: F401, E402 — registreert alle tabellen
from src.models import onboarding  # noqa: F401, E402 — registreert onboarding_responses

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Overschrijf database-URL met omgevingsvariabele
# ---------------------------------------------------------------------------
def get_url() -> str:
    """Haalt DATABASE_URL op uit omgevingsvariabelen of .env bestand."""
    try:
        from src.core.config import settings
        return settings.database_url
    except Exception:
        # Fallback voor als .env niet geladen is
        return os.getenv("DATABASE_URL", "sqlite:///./backend/db/youcaps.db")


# ---------------------------------------------------------------------------
# Offline migratie (zonder live database-verbinding)
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """
    Genereert SQL-scripts zonder database-verbinding.
    Nuttig voor het reviewen van migraties vóór uitvoer.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migratie (met live database-verbinding)
# ---------------------------------------------------------------------------
def run_migrations_online() -> None:
    """Voert migraties uit op een live database-verbinding."""
    # Overschrijf de URL in de alembic.ini-config
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Geen connection pooling tijdens migraties
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Voer de juiste modus uit
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
