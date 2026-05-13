"""
backend/db/seed.py
------------------
Database-seeder voor YouCaps.

Laadt de supplement-data uit backend/db/seed_data.json in de database.
Wordt eenmalig uitgevoerd om de database te vullen met initiële data.

Gebruik:
    python -m backend.db.seed
    # of
    python backend/db/seed.py

Idempotent: bestaande records worden NIET overschreven (skip bij duplicate).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def run_seed() -> None:
    """Laadt seed_data.json in de database."""
    from backend.db.database import SessionLocal, create_tables
    from backend.models.orm_models import (
        ContraIndicationORM,
        IngredientORM,
        SupplementORM,
    )

    # Zorg dat tabellen bestaan
    create_tables()

    seed_file = Path(__file__).parent / "seed_data.json"
    if not seed_file.exists():
        logger.error("seed_data.json niet gevonden op: %s", seed_file)
        sys.exit(1)

    with open(seed_file, encoding="utf-8") as f:
        records = json.load(f)

    db = SessionLocal()
    inserted = 0
    skipped = 0

    try:
        for record in records:
            existing = db.get(SupplementORM, record["id"])
            if existing:
                logger.debug("Skip (al aanwezig): %s", record["id"])
                skipped += 1
                continue

            pi = record["product_info"]
            al = record.get("ai_logic") or {}

            supplement = SupplementORM(
                id=record["id"],
                name=pi["name"],
                brand=pi.get("brand"),
                dosage=pi["dosage"],
                product_type=pi.get("type"),
                optimal_timing=al.get("optimal_timing"),
                primary_benefit=al.get("primary_benefit"),
                warning=al.get("warning"),
                source="seed",
                ai_generated=False,
                verified=True,  # seed-data is handmatig gecureerd
            )

            for ing in record.get("ingredients", []):
                supplement.ingredients.append(
                    IngredientORM(name=ing["name"], amount=ing.get("amount"))
                )

            for ci in record.get("contra_indications", []):
                supplement.contra_indications.append(
                    ContraIndicationORM(
                        medication_or_condition=ci["medication_or_condition"],
                        severity=ci["severity"],
                        description=ci.get("description"),
                        ai_generated=False,
                        verified=True,
                    )
                )

            db.add(supplement)
            inserted += 1
            logger.info("Toegevoegd: %s (%s)", supplement.name, supplement.id)

        db.commit()
        logger.info("Seed voltooid: %d toegevoegd, %d overgeslagen.", inserted, skipped)

    except Exception as exc:
        db.rollback()
        logger.error("Seed mislukt: %s", exc)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_seed()
