"""Tourist visa information endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models.tourist_visa_info import TouristVisaInfo
from app.api.v1.tourist_visa_schemas import (
    TouristVisaInfoResponse,
    TouristVisaInfoCreate,
)

router = APIRouter(prefix="/tourist-visa", tags=["tourist-visa"])


@router.get("/countries", response_model=List[str])
async def list_countries(db: AsyncSession = Depends(get_db)):
    """Get list of all countries with tourist visa information."""
    result = await db.execute(
        select(TouristVisaInfo.country).order_by(TouristVisaInfo.country)
    )
    countries = [row[0] for row in result.all()]
    return countries


@router.get("/{country}", response_model=TouristVisaInfoResponse)
async def get_visa_info(country: str, db: AsyncSession = Depends(get_db)):
    """Get tourist visa information for a specific country."""
    result = await db.execute(
        select(TouristVisaInfo).where(TouristVisaInfo.country == country)
    )
    visa_info = result.scalar_one_or_none()
    
    if not visa_info:
        raise HTTPException(status_code=404, detail=f"Visa information not found for {country}")
    
    return visa_info


@router.post("/", response_model=TouristVisaInfoResponse)
async def create_visa_info(
    visa_info: TouristVisaInfoCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create tourist visa information (admin only)."""
    db_visa_info = TouristVisaInfo(**visa_info.model_dump())
    db.add(db_visa_info)
    await db.commit()
    await db.refresh(db_visa_info)
    return db_visa_info
