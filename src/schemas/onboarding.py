from typing import Literal
from pydantic import BaseModel

GoalType = Literal["energy", "sleep", "muscle", "immune", "stress"]
AgeRangeType = Literal["18-25", "26-35", "36-45", "46-55", "56+"]
SexType = Literal["man", "vrouw", "anders"]
DietType = Literal["omnivoor", "vegetarisch", "veganistisch", "glutenvrij"]


class OnboardingStartRequest(BaseModel):
    goal: GoalType
    age_range: AgeRangeType
    sex: SexType
    diet: DietType


class FormulaItem(BaseModel):
    name: str
    desc: str
    dose: str


class OnboardingStartResponse(BaseModel):
    id: str
    goal: GoalType
    age_range: AgeRangeType
    sex: SexType
    diet: DietType
    formula: list[FormulaItem]


class FormulaResponse(BaseModel):
    id: str
    goal: GoalType
    age_range: AgeRangeType
    sex: SexType
    diet: DietType
    formula: list[FormulaItem]
