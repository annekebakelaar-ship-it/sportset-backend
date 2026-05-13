"""
backend/db/session.py
---------------------
Database-sessie hulpfuncties voor YouCaps.

Exporteert get_db() als FastAPI dependency en init_db() voor
eenmalige tabel-aanmaak + seeding bij opstarten.

Gebruik in FastAPI endpoints:
    from src.db.session import get_db
    from sqlalchemy.orm import Session

    @router.get("/supplements")
    def list_supplements(db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy.orm import Session

from src.db.database import SessionLocal, create_tables


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency — opent een database-sessie en sluit deze na gebruik.
    Gebruik als: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(seed: bool = False) -> None:
    """
    Initialiseert de database:
      1. Maakt alle tabellen aan (create_all — idempotent).
      2. Optioneel: laadt seed-data uit seed_data.json.

    Parameters
    ----------
    seed : bool
        Als True, wordt de seeder uitgevoerd na tabel-aanmaak.
    """
    create_tables()
    if seed:
        from src.db.seed import run_seed
        run_seed()
