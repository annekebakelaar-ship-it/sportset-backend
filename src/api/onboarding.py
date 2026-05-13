from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.models.onboarding import OnboardingResponseORM
from backend.models.orm_models import UserORM
from backend.schemas.onboarding import (
    OnboardingStartRequest,
    OnboardingStartResponse,
    FormulaResponse,
)
from backend.services.auth_service import get_current_user
from backend.services.formula_service import build_formula


router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/start", status_code=201, response_model=OnboardingStartResponse)
async def start_onboarding(
    req: OnboardingStartRequest,
    user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = OnboardingResponseORM(
        user_id=user.id,
        goal=req.goal,
        age_range=req.age_range,
        sex=req.sex,
        diet=req.diet,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return OnboardingStartResponse(
        id=record.id,
        goal=record.goal,
        age_range=record.age_range,
        sex=record.sex,
        diet=record.diet,
        formula=build_formula(record.goal, record.diet),
    )


@router.get("/formula/{onboarding_id}", response_model=FormulaResponse)
async def get_formula(
    onboarding_id: str,
    user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = db.query(OnboardingResponseORM).filter(
        OnboardingResponseORM.id == onboarding_id
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Niet gevonden")

    if record.user_id != user.id:
        raise HTTPException(status_code=403, detail="Geen toegang")

    return FormulaResponse(
        id=record.id,
        goal=record.goal,
        age_range=record.age_range,
        sex=record.sex,
        diet=record.diet,
        formula=build_formula(record.goal, record.diet),
    )
