"""Travel cost estimation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from decimal import Decimal
from pydantic import BaseModel

from app.core.database import get_db
from app.models.travel_cost import TravelCost
from app.api.v1.tourist_visa_schemas import (
    TravelCostResponse,
    TravelCostCreate,
    CostEstimateRequest,
    CostEstimateResponse,
    CostBreakdown,
)

router = APIRouter(prefix="/travel-costs", tags=["travel-costs"])


@router.post("/estimate", response_model=CostEstimateResponse)
async def estimate_travel_cost(
    request: CostEstimateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Estimate total travel cost based on country, duration, and budget tier."""
    
    # Get cost data for the country
    result = await db.execute(
        select(TravelCost).where(TravelCost.country == request.country)
    )
    costs = result.scalars().all()
    
    if not costs:
        raise HTTPException(
            status_code=404,
            detail=f"Cost data not available for {request.country}"
        )
    
    # Calculate costs by category
    breakdown = []
    total_cost = Decimal('0')
    
    # Flight costs (round trip per person)
    flight_costs = [c for c in costs if c.category == 'flight']
    if flight_costs:
        avg_flight = sum(c.cost_usd_avg for c in flight_costs if c.cost_usd_avg) / len(flight_costs)
        flight_total = avg_flight * request.travelers
        breakdown.append(CostBreakdown(
            category="Flights",
            cost_usd=flight_total,
            details=f"Round trip for {request.travelers} traveler(s)"
        ))
        total_cost += flight_total
    
    # Hotel costs (per night)
    hotel_costs = [c for c in costs if c.category == 'hotel']
    if hotel_costs:
        # Filter by budget tier if available
        tier_hotels = [c for c in hotel_costs if request.budget_tier in (c.notes or '').lower()]
        if not tier_hotels:
            tier_hotels = hotel_costs
        
        avg_hotel = sum(c.cost_usd_avg for c in tier_hotels if c.cost_usd_avg) / len(tier_hotels)
        hotel_total = avg_hotel * request.duration_days
        breakdown.append(CostBreakdown(
            category="Accommodation",
            cost_usd=hotel_total,
            details=f"{request.duration_days} nights ({request.budget_tier})"
        ))
        total_cost += hotel_total
    
    # Food costs (per day per person)
    food_costs = [c for c in costs if c.category == 'food']
    if food_costs:
        avg_food = sum(c.cost_usd_avg for c in food_costs if c.cost_usd_avg) / len(food_costs)
        food_total = avg_food * request.duration_days * request.travelers
        breakdown.append(CostBreakdown(
            category="Food",
            cost_usd=food_total,
            details=f"{request.duration_days} days for {request.travelers} person(s)"
        ))
        total_cost += food_total
    
    # Transport costs (per day)
    transport_costs = [c for c in costs if c.category == 'transport']
    if transport_costs:
        avg_transport = sum(c.cost_usd_avg for c in transport_costs if c.cost_usd_avg) / len(transport_costs)
        transport_total = avg_transport * request.duration_days
        breakdown.append(CostBreakdown(
            category="Local Transport",
            cost_usd=transport_total,
            details=f"{request.duration_days} days"
        ))
        total_cost += transport_total
    
    # Activities costs (per day)
    activity_costs = [c for c in costs if c.category == 'activities']
    if activity_costs:
        avg_activity = sum(c.cost_usd_avg for c in activity_costs if c.cost_usd_avg) / len(activity_costs)
        activity_total = avg_activity * request.duration_days * request.travelers
        breakdown.append(CostBreakdown(
            category="Activities",
            cost_usd=activity_total,
            details=f"{request.duration_days} days for {request.travelers} person(s)"
        ))
        total_cost += activity_total
    
    per_person_cost = total_cost / request.travelers if request.travelers > 0 else total_cost
    
    return CostEstimateResponse(
        country=request.country,
        duration_days=request.duration_days,
        budget_tier=request.budget_tier,
        travelers=request.travelers,
        total_cost_usd=total_cost,
        per_person_cost_usd=per_person_cost,
        breakdown=breakdown
    )


@router.get("/{country}/breakdown", response_model=List[TravelCostResponse])
async def get_cost_breakdown(
    country: str,
    category: str = None,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed cost breakdown for a country."""
    query = select(TravelCost).where(TravelCost.country == country)
    
    if category:
        query = query.where(TravelCost.category == category)
    
    result = await db.execute(query)
    costs = result.scalars().all()
    
    return costs


@router.post("/", response_model=TravelCostResponse)
async def create_travel_cost(
    cost: TravelCostCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create travel cost data (admin only)."""
    db_cost = TravelCost(**cost.model_dump())
    db.add(db_cost)
    await db.commit()
    await db.refresh(db_cost)
    return db_cost


class CostComparisonRequest(BaseModel):
    countries: List[str]
    duration_days: int = 7
    budget_tier: str = "mid-range"
    travelers: int = 1

@router.post("/compare")
async def compare_travel_costs(
    request: CostComparisonRequest,
    db: AsyncSession = Depends(get_db)
):
    """Compare travel costs across multiple countries."""
    
    if len(request.countries) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 countries for comparison")
    
    comparisons = []
    
    for country in request.countries:
        # ... logic uses request.duration_days, request.budget_tier, request.travelers
        # Get cost data
        result = await db.execute(
            select(TravelCost).where(TravelCost.country == country)
        )
        costs = result.scalars().all()
        
        if not costs:
            comparisons.append({
                "country": country,
                "error": "No cost data available",
                "total_cost_usd": None
            })
            continue
        
        # Calculate costs
        total_cost = Decimal('0')
        breakdown = {}
        
        # Flight costs
        flight_costs = [c for c in costs if c.category == 'flight']
        if flight_costs:
            avg_flight = sum(c.cost_usd_avg for c in flight_costs if c.cost_usd_avg) / len(flight_costs)
            flight_total = avg_flight * request.travelers
            breakdown["flights"] = float(flight_total)
            total_cost += flight_total
        
        # Hotel costs
        hotel_costs = [c for c in costs if c.category == 'hotel']
        if hotel_costs:
            tier_hotels = [c for c in hotel_costs if request.budget_tier in (c.notes or '').lower()]
            if not tier_hotels:
                tier_hotels = hotel_costs
            avg_hotel = sum(c.cost_usd_avg for c in tier_hotels if c.cost_usd_avg) / len(tier_hotels)
            hotel_total = avg_hotel * request.duration_days
            breakdown["accommodation"] = float(hotel_total)
            total_cost += hotel_total
        
        # Food costs
        food_costs = [c for c in costs if c.category == 'food']
        if food_costs:
            avg_food = sum(c.cost_usd_avg for c in food_costs if c.cost_usd_avg) / len(food_costs)
            food_total = avg_food * request.duration_days * request.travelers
            breakdown["food"] = float(food_total)
            total_cost += food_total
        
        # Transport costs
        transport_costs = [c for c in costs if c.category == 'transport']
        if transport_costs:
            avg_transport = sum(c.cost_usd_avg for c in transport_costs if c.cost_usd_avg) / len(transport_costs)
            transport_total = avg_transport * request.duration_days
            breakdown["transport"] = float(transport_total)
            total_cost += transport_total
        
        # Activities
        activity_costs = [c for c in costs if c.category == 'activities']
        if activity_costs:
            avg_activity = sum(c.cost_usd_avg for c in activity_costs if c.cost_usd_avg) / len(activity_costs)
            activity_total = avg_activity * request.duration_days * request.travelers
            breakdown["activities"] = float(activity_total)
            total_cost += activity_total
        
        comparisons.append({
            "country": country,
            "total_cost_usd": float(total_cost),
            "per_person_cost_usd": float(total_cost / request.travelers) if request.travelers > 0 else float(total_cost),
            "breakdown": breakdown,
            "duration_days": request.duration_days,
            "budget_tier": request.budget_tier,
            "travelers": request.travelers
        })
    
    # Sort by total cost
    comparisons.sort(key=lambda x: x.get("total_cost_usd") or float('inf'))
    
    return {
        "comparisons": comparisons,
        "cheapest": comparisons[0]["country"] if comparisons and comparisons[0].get("total_cost_usd") else None,
        "most_expensive": comparisons[-1]["country"] if comparisons and comparisons[-1].get("total_cost_usd") else None
    }
