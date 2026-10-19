"""AI-powered travel itinerary generator using the local LLM."""

import logging
from typing import Dict, List, Any
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm import llm_service
from app.services.prompt_registry import get_prompt
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost

logger = logging.getLogger(__name__)


async def generate_itinerary(
    db: AsyncSession,
    country: str,
    duration_days: int,
    budget_tier: str,
    interests: List[str] = None,
    cities: List[str] = None,
) -> Dict[str, Any]:
    """
    Generate AI-powered travel itinerary using the local LLM.
    
    Args:
        db: Database session
        country: Destination country
        duration_days: Trip duration in days
        budget_tier: 'budget', 'mid-range', or 'luxury'
        interests: List of interests (e.g., ['culture', 'food', 'adventure'])
        cities: Specific cities to visit (optional)
        
    Returns:
        Dictionary with itinerary data
    """
    
    # Fetch available destinations
    query = select(TouristDestination).where(TouristDestination.country == country)
    if cities:
        query = query.where(TouristDestination.city.in_(cities))
    
    result = await db.execute(query)
    destinations = result.scalars().all()
    
    if not destinations:
        return {
            "error": f"No destinations found for {country}",
            "itinerary": []
        }
    
    # Fetch cost data
    cost_result = await db.execute(
        select(TravelCost).where(TravelCost.country == country)
    )
    costs = cost_result.scalars().all()
    
    # Build context for AI
    destinations_info = []
    for dest in destinations:
        destinations_info.append({
            "name": dest.name,
            "city": dest.city,
            "category": dest.category,
            "rating": float(dest.rating) if dest.rating else 0,
            "estimated_time": dest.estimated_time,
            "entry_fee": float(dest.entry_fee_usd) if dest.entry_fee_usd else 0,
            "description": dest.description,
            "best_time": dest.best_time_to_visit
        })
    
    # Build cost context
    avg_daily_food = 0
    avg_daily_transport = 0
    avg_hotel = 0
    
    for cost in costs:
        if cost.category == 'food' and cost.cost_usd_avg:
            avg_daily_food = float(cost.cost_usd_avg)
        elif cost.category == 'transport' and cost.cost_usd_avg:
            avg_daily_transport = float(cost.cost_usd_avg)
        elif cost.category == 'hotel' and cost.cost_usd_avg:
            if budget_tier in (cost.notes or '').lower():
                avg_hotel = float(cost.cost_usd_avg)
    
    # Create AI prompt
    interests_str = ", ".join(interests) if interests else "general sightseeing"
    
    destination_lines = "\n".join(
        f"- {d['name']} ({d['city']}): {d['description'][:100]}... Rating: {d['rating']}, "
        f"Time needed: {d['estimated_time']}, Entry: ${d['entry_fee']}"
        for d in destinations_info[:10]
    )
    # Prompt text: app/prompts/itinerary.yaml (M0.12)
    system_prompt, user_prompt = get_prompt("itinerary").render(
        duration_days=duration_days, country=country, budget_tier=budget_tier, interests=interests_str,
        destination_count=len(destinations), destination_lines=destination_lines, avg_daily_food=avg_daily_food,
        avg_daily_transport=avg_daily_transport, avg_hotel=avg_hotel,
    )
    
    try:
        # Generate itinerary using the local LLM
        # Streamed collection: a long itinerary must not hit the non-streaming total timeout (2026-10-15 review)
        response = await llm_service.generate_long_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.8,
            max_tokens=4000,
            role="itinerary",
        )
        
        # Parse JSON response
        import json
        
        # Clean response (remove markdown code blocks if present)
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
        
        itinerary_data = json.loads(response)
        
        return {
            "success": True,
            "country": country,
            "duration_days": duration_days,
            "budget_tier": budget_tier,
            "interests": interests or [],
            "itinerary": itinerary_data,
            "destinations_used": [d["name"] for d in destinations_info[:10]]
        }
        
    except json.JSONDecodeError as e:
        logger.warning(f"[ITINERARY] JSON parse error: {e}")
        logger.debug(f"[ITINERARY] Response: {response[:500]}")
        return {
            "success": False,
            "error": "Failed to parse AI response",
            "raw_response": response[:500]
        }
    except Exception as e:
        logger.warning(f"[ITINERARY] Error generating itinerary: {e}")
        return {
            "success": False,
            "error": str(e)
        }
