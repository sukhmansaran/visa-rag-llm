"""Travel destinations and itinerary endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.tourist_destination import TouristDestination
from app.api.v1.tourist_visa_schemas import (
    TouristDestinationResponse,
    TouristDestinationCreate,
)
from app.services.itinerary_generator import generate_itinerary

router = APIRouter(prefix="/travel", tags=["travel"])


# Itinerary request schema
class ItineraryGenerateRequest(BaseModel):
    country: str
    duration_days: int = Field(gt=0, le=30)
    budget_tier: str = Field(pattern="^(budget|mid-range|luxury)$")
    interests: Optional[List[str]] = None
    cities: Optional[List[str]] = None


@router.get("/destinations/{country}", response_model=List[TouristDestinationResponse])
async def get_destinations_by_country(
    country: str,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get tourist destinations for a country, optionally filtered by category."""
    query = select(TouristDestination).where(TouristDestination.country == country)
    
    if category:
        query = query.where(TouristDestination.category == category)
    
    query = query.order_by(TouristDestination.rating.desc())
    
    result = await db.execute(query)
    destinations = result.scalars().all()
    
    return destinations


@router.get("/destinations/{country}/{city}", response_model=List[TouristDestinationResponse])
async def get_destinations_by_city(
    country: str,
    city: str,
    db: AsyncSession = Depends(get_db)
):
    """Get tourist destinations for a specific city."""
    result = await db.execute(
        select(TouristDestination)
        .where(
            TouristDestination.country == country,
            TouristDestination.city == city
        )
        .order_by(TouristDestination.rating.desc())
    )
    destinations = result.scalars().all()
    
    return destinations


@router.post("/destinations", response_model=TouristDestinationResponse)
async def create_destination(
    destination: TouristDestinationCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a tourist destination (admin only)."""
    db_destination = TouristDestination(**destination.model_dump())
    db.add(db_destination)
    await db.commit()
    await db.refresh(db_destination)
    return db_destination



@router.post("/itinerary/generate", response_model=Dict[str, Any])
async def generate_travel_itinerary(
    request: ItineraryGenerateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generate AI-powered travel itinerary."""
    try:
        itinerary = await generate_itinerary(
            db=db,
            country=request.country,
            duration_days=request.duration_days,
            budget_tier=request.budget_tier,
            interests=request.interests,
            cities=request.cities
        )
        return itinerary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate itinerary: {str(e)}")
