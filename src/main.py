"""
Youcaps API — FastAPI Main Entry Point
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from src.api.auth import router as auth_router
from src.api.scans import router as scans_router
from src.api.onboarding import router as onboarding_router
from src.api.oura import router as oura_router



# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle"""
    logger.info("Youcaps API starting...")
    from src.db.database import create_tables
    create_tables()
    yield
    logger.info("Youcaps API shutting down...")

# Create FastAPI app
app = FastAPI(
    title="Youcaps API",
    description="Gepersonaliseerde supplement-service",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(scans_router)
# Bij de andere include_router calls:
app.include_router(onboarding_router)
app.include_router(oura_router)


@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
