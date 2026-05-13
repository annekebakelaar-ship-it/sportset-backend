"""
Scans API — User Supplement History
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List

from src.db.database import get_db
from src.services.auth_service import get_current_user
from src.models.orm_models import UserORM, UserScanORM


router = APIRouter(prefix="/scans", tags=["scans"])


# Request/Response Models
class ScanItemCreate(BaseModel):
    supplement: str
    note: str | None = None


class ScanItem(BaseModel):
    id: str
    supplement: str
    note: str | None
    created_at: str

    class Config:
        from_attributes = True


class ScansList(BaseModel):
    scans: List[ScanItem]
    total: int


# Endpoints
@router.post("", status_code=201, response_model=ScanItem)
async def create_scan(
    req: ScanItemCreate,
    user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new supplement scan"""
    scan = UserScanORM(
        user_id=user.id,
        supplement=req.supplement,
        note=req.note,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


@router.get("", response_model=ScansList)
async def list_scans(
    user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all scans for current user"""
    scans = db.query(UserScanORM).filter(UserScanORM.user_id == user.id).all()
    return {"scans": scans, "total": len(scans)}


@router.delete("/{scan_id}", status_code=204)
async def delete_scan(
    scan_id: str,
    user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a specific scan"""
    scan = db.query(UserScanORM).filter(
        UserScanORM.id == scan_id,
        UserScanORM.user_id == user.id,
    ).first()
    
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    
    db.delete(scan)
    db.commit()
