"""
Sportset API — Minimal MVP
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Sportset API",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "message": "Sportset API running"}

@app.get("/api/oura/sleep")
async def mock_sleep():
    """Mock Oura sleep data"""
    return {
        "sleep": [
            {"date": "2024-05-14", "duration": 7.5, "quality": 85}
        ]
    }

@app.get("/api/oura/activity")
async def mock_activity():
    """Mock Oura activity data"""
    return {
        "activity": [
            {"date": "2024-05-14", "steps": 8234, "calories": 520}
        ]
    }

@app.get("/api/oura/heart-rate")
async def mock_heart_rate():
    """Mock Oura heart rate data"""
    return {
        "heart_rate": [
            {"date": "2024-05-14", "avg": 68, "max": 95, "min": 52}
        ]
    }
