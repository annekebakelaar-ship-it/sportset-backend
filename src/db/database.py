"""
backend/db/database.py
----------------------
SQLAlchemy database-configuratie voor YouCaps.

Ondersteunt:
  - SQLite  (development, geen extra installatie)
  - PostgreSQL (productie, via DATABASE_URL in .env)

Gebruik:
    from src.db.database import get_db, engine

    # In FastAPI endpoint als dependency:
    def my_endpoint(db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine aanmaken
# ---------------------------------------------------------------------------

def _build_engine():
    """Bouwt de SQLAlchemy engine op basis van DATABASE_URL."""
    url = settings.database_url
    kwargs: dict = {}

    if url.startswith("sqlite"):
        # SQLite-specifieke instellingen:
        # - check_same_thread=False zodat meerdere FastAPI-threads dezelfde connectie mogen gebruiken
        # - WAL-modus wordt ingesteld via een event-hook (zie hieronder)
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, echo=settings.debug, **kwargs)

    # Zet WAL-modus aan voor SQLite (betere concurrency, minder lock-conflicten)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_wal_mode(dbapi_conn, connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _build_engine()

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ---------------------------------------------------------------------------
# Base class voor ORM-modellen
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """
    Basis-klasse voor alle SQLAlchemy ORM-modellen.
    Alle modellen erven van deze klasse.
    """
    pass


# ---------------------------------------------------------------------------
# Tabel-aanmaak
# ---------------------------------------------------------------------------

def create_tables() -> None:
    """
    Maakt alle database-tabellen aan als ze nog niet bestaan.
    Wordt aangeroepen bij applicatie-startup (zie backend/main.py lifespan).

    In productie: gebruik Alembic-migraties i.p.v. create_all().
    """
    from src.models import orm_models, onboarding  # noqa: F401 — importeer zodat tabellen geregistreerd zijn   # noqa: F401 — importeer zodat tabellen geregistreerd zijn
    Base.metadata.create_all(bind=engine)
    logger.info("Database-tabellen aangemaakt (create_all).")


# ---------------------------------------------------------------------------
# Database health-check
# ---------------------------------------------------------------------------

def check_db_connection() -> bool:
    """
    Controleert of de database bereikbaar is.
    Retourneert True als verbinding lukt, anders False.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health-check mislukt: %s", exc)
        return False


# ---------------------------------------------------------------------------
# FastAPI dependency — gebruik in endpoints
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency die een database-sessie opent en na gebruik sluit.

    Gebruik:
        from fastapi import Depends
        from src.db.database import get_db

        @router.get("/supplements")
        def list_supplements(db: Session = Depends(get_db)):
            return db.query(SupplementORM).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
