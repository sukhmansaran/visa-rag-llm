"""Integrated tour package endpoints - combines visa, destinations, costs, and itinerary."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from decimal import Decimal

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.travel_itinerary import TravelItinerary
from app.models.tourist_visa_info import TouristVisaInfo
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost
from app.services.itinerary_generator import generate_itinerary

router = APIRouter(prefix="/tour-packages", tags=["tour-packages"])


class TourPackageRequest(BaseModel):
    """Request to create a complete tour package."""
    country: str
    duration_days: int = Field(gt=0, le=30)
    budget_tier: str = Field(pattern="^(budget|mid-range|luxury)$")
    interests: Optional[List[str]] = None
    cities: Optional[List[str]] = None
    travelers: int = Field(default=1, gt=0, le=20)
    include_visa_info: bool = True


class TourPackageResponse(BaseModel):
    """Complete tour package with all information."""
    id: int
    country: str
    duration_days: int
    budget_tier: str
    travelers: int
    
    # Visa Information
    visa_info: Optional[Dict[str, Any]] = None
    
    # Destinations
    destinations: List[Dict[str, Any]] = []
    
    # Cost Breakdown
    total_cost_usd: Decimal
    per_person_cost_usd: Decimal
    cost_breakdown: Dict[str, Any]
    
    # AI-Generated Itinerary
    itinerary: Dict[str, Any]
    
    # Status
    status: str
    created_at: str


@router.post("/create", response_model=TourPackageResponse)
async def create_complete_tour_package(
    request: TourPackageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a complete integrated tour package.
    
    This endpoint combines:
    1. Visa requirements
    2. Tourist destinations
    3. Cost estimation
    4. AI-generated itinerary
    
    Everything in one cohesive package!
    """
    
    print(f"[TOUR PACKAGE] Creating package for {request.country}, {request.duration_days} days")
    
    # 1. Get Visa Information
    visa_info_dict = None
    if request.include_visa_info:
        result = await db.execute(
            select(TouristVisaInfo).where(TouristVisaInfo.country == request.country)
        )
        visa_info = result.scalar_one_or_none()
        if visa_info:
            visa_info_dict = {
                "visa_required": visa_info.visa_required,
                "visa_types": visa_info.visa_types,
                "processing_time": visa_info.processing_time,
                "visa_fee_usd": float(visa_info.visa_fee_usd) if visa_info.visa_fee_usd else None,
                "requirements": visa_info.requirements,
                "application_process": visa_info.application_process,
                "official_website": visa_info.official_website
            }
    
    # 2. Get Tourist Destinations
    dest_query = select(TouristDestination).where(TouristDestination.country == request.country)
    if request.cities:
        dest_query = dest_query.where(TouristDestination.city.in_(request.cities))
    dest_query = dest_query.order_by(TouristDestination.rating.desc()).limit(10)
    
    dest_result = await db.execute(dest_query)
    destinations = dest_result.scalars().all()
    
    destinations_list = [
        {
            "name": d.name,
            "city": d.city,
            "category": d.category,
            "rating": float(d.rating) if d.rating else None,
            "entry_fee_usd": float(d.entry_fee_usd) if d.entry_fee_usd else None,
            "description": d.description
        }
        for d in destinations
    ]
    
    # 3. Calculate Costs
    cost_result = await db.execute(
        select(TravelCost).where(TravelCost.country == request.country)
    )
    costs = cost_result.scalars().all()
    
    total_cost = Decimal('0')
    cost_breakdown = {}
    
    if costs:
        # Flight costs
        flight_costs = [c for c in costs if c.category == 'flight']
        if flight_costs:
            avg_flight = sum(c.cost_usd_avg for c in flight_costs if c.cost_usd_avg) / len(flight_costs)
            flight_total = avg_flight * request.travelers
            cost_breakdown["flights"] = float(flight_total)
            total_cost += flight_total
        
        # Hotel costs
        hotel_costs = [c for c in costs if c.category == 'hotel']
        if hotel_costs:
            tier_hotels = [c for c in hotel_costs if request.budget_tier in (c.notes or '').lower()]
            if not tier_hotels:
                tier_hotels = hotel_costs
            avg_hotel = sum(c.cost_usd_avg for c in tier_hotels if c.cost_usd_avg) / len(tier_hotels)
            hotel_total = avg_hotel * request.duration_days
            cost_breakdown["accommodation"] = float(hotel_total)
            total_cost += hotel_total
        
        # Food, transport, activities
        for category in ['food', 'transport', 'activities']:
            cat_costs = [c for c in costs if c.category == category]
            if cat_costs:
                avg_cost = sum(c.cost_usd_avg for c in cat_costs if c.cost_usd_avg) / len(cat_costs)
                if category in ['food', 'activities']:
                    total_cat = avg_cost * request.duration_days * request.travelers
                else:
                    total_cat = avg_cost * request.duration_days
                cost_breakdown[category] = float(total_cat)
                total_cost += total_cat
    
    per_person_cost = total_cost / request.travelers if request.travelers > 0 else total_cost
    
    # 4. Generate AI Itinerary
    print(f"[TOUR PACKAGE] Generating AI itinerary...")
    itinerary_result = await generate_itinerary(
        db=db,
        country=request.country,
        duration_days=request.duration_days,
        budget_tier=request.budget_tier,
        interests=request.interests,
        cities=request.cities
    )
    
    if not itinerary_result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to generate itinerary")
    
    itinerary_data = itinerary_result.get("itinerary", {})
    
    # 5. Save Everything as a Travel Itinerary
    travel_itinerary = TravelItinerary(
        user_id=current_user.id,
        country=request.country,
        duration_days=request.duration_days,
        budget_tier=request.budget_tier,
        interests={"interests": request.interests or []},
        generated_by='ai',
        itinerary_data=itinerary_data,
        destinations_included={"destinations": [d["name"] for d in destinations_list]},
        total_cost_usd=total_cost,
        visa_info_included=visa_info_dict is not None,
        status='draft'
    )
    
    db.add(travel_itinerary)
    await db.commit()
    await db.refresh(travel_itinerary)
    
    print(f"[TOUR PACKAGE] ✓ Complete package created with ID {travel_itinerary.id}")
    
    # 6. Return Complete Package
    return TourPackageResponse(
        id=travel_itinerary.id,
        country=request.country,
        duration_days=request.duration_days,
        budget_tier=request.budget_tier,
        travelers=request.travelers,
        visa_info=visa_info_dict,
        destinations=destinations_list,
        total_cost_usd=total_cost,
        per_person_cost_usd=per_person_cost,
        cost_breakdown=cost_breakdown,
        itinerary=itinerary_data,
        status=travel_itinerary.status,
        created_at=travel_itinerary.created_at.isoformat()
    )


@router.get("/my-packages", response_model=List[Dict[str, Any]])
async def get_my_tour_packages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all tour packages for the current user."""
    result = await db.execute(
        select(TravelItinerary)
        .where(TravelItinerary.user_id == current_user.id)
        .order_by(TravelItinerary.created_at.desc())
    )
    packages = result.scalars().all()
    
    return [
        {
            "id": p.id,
            "country": p.country,
            "duration_days": p.duration_days,
            "budget_tier": p.budget_tier,
            "total_cost_usd": float(p.total_cost_usd) if p.total_cost_usd else None,
            "status": p.status,
            "created_at": p.created_at.isoformat()
        }
        for p in packages
    ]


@router.get("/{package_id}", response_model=TourPackageResponse)
async def get_tour_package(
    package_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific tour package by ID."""
    result = await db.execute(
        select(TravelItinerary).where(TravelItinerary.id == package_id)
    )
    package = result.scalar_one_or_none()
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    if package.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Reconstruct the response
    return TourPackageResponse(
        id=package.id,
        country=package.country,
        duration_days=package.duration_days or 0,
        budget_tier=package.budget_tier or "mid-range",
        travelers=1,  # Default, not stored separately
        visa_info={} if package.visa_info_included else None,
        destinations=package.destinations_included.get("destinations", []) if package.destinations_included else [],
        total_cost_usd=package.total_cost_usd or Decimal('0'),
        per_person_cost_usd=package.total_cost_usd or Decimal('0'),
        cost_breakdown={},
        itinerary=package.itinerary_data or {},
        status=package.status,
        created_at=package.created_at.isoformat()
    )
