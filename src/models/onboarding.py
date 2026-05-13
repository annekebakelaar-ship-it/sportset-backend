import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from backend.db.database import Base


class OnboardingResponseORM(Base):
    __tablename__ = "onboarding_responses"
    id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    goal       = Column(String(20),  nullable=False)
    age_range  = Column(String(10),  nullable=False)
    sex        = Column(String(20),  nullable=False)
    diet       = Column(String(20),  nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())