"""
backend/api/supplements.py
--------------------------
REST endpoints voor supplement-catalogus.

GET /api/supplements        — lijst alle supplementen
GET /api/supplements/{id}   — één supplement met ingrediënten en contra-indicaties
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from backend.db.database import get_db
from backend.models.orm_models import SupplementORM

router = APIRouter(prefix="/supplements", tags=["supplements"])


# ---------------------------------------------------------------------------
# Response-schema's (Pydantic)
# ---------------------------------------------------------------------------

class IngredientOut(BaseModel):
    id: str
    name: str
    amount: Optional[str] = None
    unit: Optional[str] = None

    model_config = {"from_attributes": True}


class ContraIndicationOut(BaseModel):
    id: str
    medication_or_condition: str
    severity: str
    description: Optional[str] = None
    evidence_level: Optional[str] = None
    verified: bool

    model_config = {"from_attributes": True}


class SupplementOut(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    dosage: str
    product_type: Optional[str] = None
    optimal_timing: Optional[str] = None
    primary_benefit: Optional[str] = None
    warning: Optional[str] = None
    source: str
    ai_generated: bool
    verified: bool
    ingredients: List[IngredientOut] = []
    contra_indications: List[ContraIndicationOut] = []

    model_config = {"from_attributes": True}


class SupplementListItem(BaseModel):
    """Compacte weergave voor de lijstpagina (zonder ingrediënten/CI's)."""
    id: str
    name: str
    brand: Optional[str] = None
    dosage: str
    product_type: Optional[str] = None
    primary_benefit: Optional[str] = None
    warning: Optional[str] = None
    verified: bool
    ai_generated: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[SupplementListItem], summary="Lijst alle supplementen")
def list_supplements(db: Session = Depends(get_db)) -> list:
    """
    Retourneert alle supplementen in de catalogus (compacte weergave).
    Gesorteerd op naam.
    """
    supplements = (
        db.query(SupplementORM)
        .order_by(SupplementORM.name)
        .all()
    )
    return supplements


@router.get(
    "/{supplement_id}",
    response_model=SupplementOut,
    summary="Één supplement met details",
)
def get_supplement(supplement_id: str, db: Session = Depends(get_db)) -> SupplementORM:
    """
    Retourneert één supplement inclusief ingrediënten en contra-indicaties.
    """
    supplement = (
        db.query(SupplementORM)
        .options(
            selectinload(SupplementORM.ingredients),
            selectinload(SupplementORM.contra_indications),
        )
        .filter(SupplementORM.id == supplement_id)
        .first()
    )
    if not supplement:
        raise HTTPException(status_code=404, detail="Supplement niet gevonden.")
    return supplement
