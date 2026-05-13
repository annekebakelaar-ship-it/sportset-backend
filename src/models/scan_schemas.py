"""
backend/models/scan_schemas.py
------------------------------
Pydantic-schema's specifiek voor de Vision Scanner-pipeline (Fase 3).

Deze schema's zijn los gehouden van het bestaande `schema.py` (catalogus-modellen)
om de scope helder te houden:

  • ScanExtraction       — exact wat Claude Vision teruggeeft (rauwe extractie)
  • ScannedIngredient    — één ingrediënt zoals geëxtraheerd uit het etiket
  • IngredientMatch      — resultaat van matching tegen de knowledge base
  • ScanRisk             — geverifieerd interactie-/contraindicatie-risico
  • ScanResponse         — finaal API-antwoord aan de frontend
  • ScanErrorResponse    — gestandaardiseerd foutformaat

Confidence-scores zijn altijd in [0.0, 1.0]. Onbekende waarden zijn `None`,
nooit "onbekend" of een lege string — zo blijft downstream-logica consistent.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 1. Rauwe AI-extractie (zoals Claude antwoordt)
# ---------------------------------------------------------------------------

class ScannedIngredient(BaseModel):
    """Één ingrediënt zoals door de AI geëxtraheerd uit een etiket."""

    name: str = Field(
        ...,
        description="Letterlijke ingrediëntnaam zoals op het etiket",
        min_length=1,
        max_length=300,
    )
    normalized_name: Optional[str] = Field(
        None,
        description="Door AI voorgestelde canonieke vorm (lowercase, ontleed)",
        max_length=300,
    )
    dosage: Optional[str] = Field(
        None,
        description="Numerieke dosering als string (bijv. '500')",
        max_length=50,
    )
    unit: Optional[str] = Field(
        None,
        description="Eenheid (bijv. 'mg', 'µg', 'IU', '%')",
        max_length=20,
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="AI-zelfvertrouwen voor dit ingrediënt (0.0–1.0)",
    )

    @field_validator("name", "normalized_name", "dosage", "unit", mode="before")
    @classmethod
    def _strip_or_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class ScanExtraction(BaseModel):
    """
    Het Pydantic-contract voor wat Claude Vision MOET teruggeven.
    Strikt: extra velden worden geweigerd zodat hallucinaties geen schade aanrichten.
    """

    model_config = {"extra": "ignore"}

    product_name: Optional[str] = Field(None, max_length=300)
    brand: Optional[str] = Field(None, max_length=200)
    serving_size: Optional[str] = Field(
        None,
        max_length=200,
        description="Vrije-tekst portiegrootte, bijv. '1 capsule per dag'",
    )
    unit_count: Optional[int] = Field(
        None,
        ge=0,
        le=100000,
        description="Totaal aantal capsules/tabletten in verpakking",
    )
    ingredients: List[ScannedIngredient] = Field(default_factory=list, max_length=200)
    warnings: List[str] = Field(default_factory=list, max_length=50)
    usage_instructions: Optional[str] = Field(None, max_length=2000)
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Algeheel AI-zelfvertrouwen voor deze extractie",
    )

    @field_validator("product_name", "brand", "serving_size", "usage_instructions", mode="before")
    @classmethod
    def _strip_or_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("warnings", mode="before")
    @classmethod
    def _clean_warnings(cls, v):
        if not isinstance(v, list):
            return []
        cleaned = []
        for item in v:
            if isinstance(item, str):
                item = item.strip()
                if item:
                    cleaned.append(item[:500])
        return cleaned[:50]


# ---------------------------------------------------------------------------
# 2. Matching-resultaten
# ---------------------------------------------------------------------------

class IngredientMatch(BaseModel):
    """
    Resultaat van het matchen van één AI-ingrediënt tegen de knowledge base
    en/of de supplements-database.
    """

    extracted: ScannedIngredient = Field(
        ...,
        description="De rauwe AI-extractie waar deze match bij hoort",
    )
    canonical_key: Optional[str] = Field(
        None,
        description="Canonieke sleutel uit de knowledge base (bijv. 'magnesium')",
    )
    canonical_name: Optional[str] = Field(
        None,
        description="Mens-leesbare canonieke naam",
    )
    match_score: float = Field(0.0, ge=0.0, le=1.0)
    match_quality: str = Field(
        "unmatched",
        description="strong | weak | unmatched",
        pattern="^(strong|weak|unmatched)$",
    )
    db_supplement_ids: List[str] = Field(
        default_factory=list,
        description="ID's van bestaande supplements in de catalogus die dit ingrediënt bevatten",
    )


class ScanRisk(BaseModel):
    """
    Een geverifieerde contra-indicatie / interactie afkomstig uit de knowledge base.
    Komt nooit rechtstreeks van de AI — bewuste mitigatie van R-003 (AI-hallucinatie
    als medische autoriteit).
    """

    canonical_key: str = Field(..., description="Sleutel van het betrokken ingrediënt")
    canonical_name: str = Field(..., description="Mens-leesbare naam")
    target: str = Field(..., description="Medicijn, klasse of aandoening")
    target_type: Optional[str] = Field(None, description="medication | medication_class | condition | allergen")
    severity: str = Field(
        ...,
        description="low | medium | high | critical",
        pattern="^(low|medium|high|critical)$",
    )
    mechanism: Optional[str] = None
    clinical_effect: Optional[str] = None
    management: Optional[str] = None
    evidence_level: Optional[str] = Field(None, pattern="^[A-D]$")
    sources: List[str] = Field(default_factory=list)
    interaction_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 3. Volledig API-antwoord
# ---------------------------------------------------------------------------

class ScanMeta(BaseModel):
    """Metadata over de scan zelf — handig voor debugging en audit."""

    scan_id: str
    model: str
    latency_ms: int = Field(..., ge=0)
    image_hash: str = Field(..., min_length=64, max_length=64)
    image_bytes: int = Field(..., ge=0)
    created_at: datetime
    ai_attempts: int = Field(1, ge=1, le=10)


class ScanResponse(BaseModel):
    """Wat de frontend ontvangt na een succesvolle upload."""

    success: bool = True
    extraction: ScanExtraction
    matches: List[IngredientMatch] = Field(default_factory=list)
    risks: List[ScanRisk] = Field(default_factory=list)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    disclaimer: str = (
        "Deze analyse wordt gegenereerd door AI en is informatief. "
        "Raadpleeg altijd een arts of apotheker voor medisch advies."
    )
    meta: ScanMeta


# ---------------------------------------------------------------------------
# 4. Foutformaat
# ---------------------------------------------------------------------------

class ScanErrorResponse(BaseModel):
    """Gestandaardiseerd foutformaat voor de scanner-API."""

    success: bool = False
    error_code: str = Field(
        ...,
        description=(
            "upload_too_large | invalid_image | unsupported_image_format | "
            "ai_timeout | ai_invalid_response | ai_unavailable | "
            "rate_limited | internal_error"
        ),
    )
    message: str
    detail: Optional[str] = None
