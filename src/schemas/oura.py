from typing import Optional
from pydantic import BaseModel


class DailyDataPoint(BaseModel):
    date: str
    hrv_ms: Optional[float] = None
    sleep_latency_min: Optional[float] = None
    deep_sleep_min: Optional[float] = None
    total_sleep_min: Optional[float] = None
    active_kcal: Optional[int] = None
    steps: Optional[int] = None
    wrist_temp_deviation_c: Optional[float] = None


class OuraPullResponse(BaseModel):
    data: list[DailyDataPoint]
    pulled_at: str


class OuraStatusResponse(BaseModel):
    connected: bool
    expires_at: Optional[str] = None
