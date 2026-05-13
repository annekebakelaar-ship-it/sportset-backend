"""
backend/models/schema.py
------------------------
Pydantic data models voor de YouCaps Supplements API.
Definieert de volledige structuur van een supplement, inclusief
product-info, AI-logica, ingrediënten en contra-indicaties.

Gemigreerd vanuit: /schema.py (kladblok-versie)
Fase: 1 – Discovery (schema overgenomen ongewijzigd; refactoring in Fase 2)
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


# ---------------------------------------------------------------------------
# Sub-modellen
# ---------------------------------------------------------------------------

class ProductInfo(BaseModel):
    """Basisinformatie over het product zoals op het etiket staat."""
    name: str = Field(..., description="Naam van het supplement (bijv. 'Melatonine')")
    brand: Optional[str] = Field(None, description="Merknaam (bijv. 'Kruidvat')")
    dosage: str = Field(..., description="Dosering per eenheid (bijv. '0.29mg', '500mg')")
    type: Optional[str] = Field(None, description="Vorm: Tablet, Capsule, Poeder, Vloeistof …")


class AILogic(BaseModel):
    """Door AI gegenereerde adviezen en waarschuwingen."""
    optimal_timing: Optional[str] = Field(None, description="Beste moment van inname")
    primary_benefit: Optional[str] = Field(None, description="Voornaamste gezondheidsvoordeel")
    warning: Optional[str] = Field(None, description="Algemene waarschuwing of voorzorgsmaatregel")


class Ingredient(BaseModel):
    """Eén ingrediënt met naam en optionele hoeveelheid."""
    name: str = Field(..., description="Naam van het ingrediënt")
    amount: Optional[str] = Field(None, description="Hoeveelheid (bijv. '100mg', '10%')")


class ContraIndication(BaseModel):
    """Contra-indicatie: combinatie met medicijn of aandoening die gevaarlijk kan zijn."""
    medication_or_condition: str = Field(
        ..., description="Naam van het medicijn of de aandoening"
    )
    severity: str = Field(
        "medium",
        description="Ernst: 'low' | 'medium' | 'high'",
        pattern="^(low|medium|high)$",
    )
    description: Optional[str] = Field(None, description="Toelichting op de interactie")


# ---------------------------------------------------------------------------
# Hoofd-model
# ---------------------------------------------------------------------------

class Supplement(BaseModel):
    """Volledig supplement-object zoals opgeslagen in de database."""
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unieke identifier (UUID of leesbare slug)",
    )
    product_info: ProductInfo
    ai_logic: Optional[AILogic] = None
    ingredients: List[Ingredient] = Field(default_factory=list)
    contra_indications: List[ContraIndication] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "id": "kruidvat-melatonine-029",
                "product_info": {
                    "name": "Melatonine",
                    "brand": "Kruidvat",
                    "dosage": "0.29mg",
                    "type": "Tablet",
                },
                "ai_logic": {
                    "optimal_timing": "30-60 minuten voor het slapengaan",
                    "primary_benefit": "Bevordert de slaapbereidheid",
                    "warning": "Niet gebruiken bij auto-immuunziekten zonder overleg.",
                },
                "ingredients": [
                    {"name": "Melatonine", "amount": "0.29mg"},
                    {"name": "Microkristallijne cellulose", "amount": None},
                ],
                "contra_indications": [
                    {
                        "medication_or_condition": "Warfarine",
                        "severity": "medium",
                        "description": "Kan de bloedverdunnende werking beïnvloeden.",
                    }
                ],
            }
        }


# ---------------------------------------------------------------------------
# Request / Response helpers
# ---------------------------------------------------------------------------

class SupplementCreate(BaseModel):
    """Body voor POST /supplements – id wordt automatisch aangemaakt."""
    product_info: ProductInfo
    ai_logic: Optional[AILogic] = None
    ingredients: List[Ingredient] = Field(default_factory=list)
    contra_indications: List[ContraIndication] = Field(default_factory=list)


class ScanRequest(BaseModel):
    """Body voor POST /scan – ruwe etikettekst die door AI wordt verwerkt."""
    raw_text: str = Field(
        ...,
        description="Ruwe tekst van een supplement-etiket",
        min_length=10,
    )


class SafetyCheckRequest(BaseModel):
    """Body voor POST /safety-check – controleer interacties met medicijnen."""
    supplement_id: str = Field(..., description="ID van het supplement in de database")
    medications: List[str] = Field(
        ...,
        description="Lijst van medicijnen die de gebruiker gebruikt",
        min_length=1,
    )


class SafetyCheckResult(BaseModel):
    """Resultaat van de veiligheidscontrole."""
    supplement_id: str
    supplement_name: str
    medications_checked: List[str]
    conflicts: List[ContraIndication]
    safe: bool
    message: str


class AIAdviceRequest(BaseModel):
    """Body voor POST /advice – vraag AI-advies over een supplement in de DB."""
    supplement_id: str = Field(..., description="ID van het supplement")
    user_question: Optional[str] = Field(
        None, description="Optionele specifieke vraag van de gebruiker"
    )
