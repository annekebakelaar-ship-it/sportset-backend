# models package — Pydantic-schema's en SQLAlchemy ORM-modellen

from src.models.schema import (
    ProductInfo,
    AILogic,
    Ingredient,
    ContraIndication,
    Supplement,
    SupplementCreate,
    ScanRequest,
    SafetyCheckRequest,
    SafetyCheckResult,
    AIAdviceRequest,
)

# ORM-modellen importeren zodat ze geregistreerd zijn in Base.metadata
from src.models import orm_models  # noqa: F401

__all__ = [
    # Pydantic-schema's
    "ProductInfo",
    "AILogic",
    "Ingredient",
    "ContraIndication",
    "Supplement",
    "SupplementCreate",
    "ScanRequest",
    "SafetyCheckRequest",
    "SafetyCheckResult",
    "AIAdviceRequest",
    # ORM-modellen (via orm_models module)
    "orm_models",
]
