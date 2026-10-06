"""AI-powered travel itinerary generator using Gemini."""

from typing import Dict, List, Any
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm import llm_service
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost


async def generate_itinerary(
    db: AsyncSession,
    country: str,
    duration_days: int,
    budget_tier: str,
    interests: List[str] = None,
    cities: List[str] = None,
) -> Dict[str, Any]:
    """
    Generate AI-powered travel itinerary using Gemini.
    
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
    
    system_prompt = """You are an expert travel planner. Create detailed, practical day-by-day itineraries 
that are realistic and enjoyable. Consider travel time between locations, opening hours, and energy levels.
Format your response as a structured JSON with this exact format:

{
  "title": "Trip title",
  "overview": "Brief overview",
  "daily_budget": estimated daily cost in USD,
  "days": [
    {
      "day": 1,
      "title": "Day title",
      "activities": [
        {
          "time": "09:00",
          "activity": "Activity name",
          "location": "Location name",
          "duration": "2 hours",
          "cost": 25.00,
          "notes": "Any tips or notes"
        }
      ],
      "meals": {
        "breakfast": "Suggestion",
        "lunch": "Suggestion",
        "dinner": "Suggestion"
      },
      "accommodation": "Hotel suggestion",
      "daily_cost": 150.00
    }
  ],
  "tips": ["Tip 1", "Tip 2"],
  "total_estimated_cost": 1000.00
}"""
    
    user_prompt = f"""Create a {duration_days}-day travel itinerary for {country}.

Budget Tier: {budget_tier}
Interests: {interests_str}
Available Destinations: {len(destinations)}

Destinations to include:
{chr(10).join([f"- {d['name']} ({d['city']}): {d['description'][:100]}... Rating: {d['rating']}, Time needed: {d['estimated_time']}, Entry: ${d['entry_fee']}" for d in destinations_info[:10]])}

Cost Context:
- Average daily food: ${avg_daily_food}
- Average daily transport: ${avg_daily_transport}
- Average hotel per night: ${avg_hotel}

Create a realistic, enjoyable itinerary that:
1. Balances activities throughout each day
2. Includes travel time between locations
3. Suggests specific restaurants and hotels
4. Provides practical tips
5. Stays within the {budget_tier} budget
6. Focuses on the user's interests: {interests_str}

Return ONLY valid JSON, no additional text."""
    
    try:
        # Generate itinerary using Gemini
        response = await llm_service.generate_answer(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.8,
            max_tokens=4000
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
        print(f"[ITINERARY] JSON parse error: {e}")
        print(f"[ITINERARY] Response: {response[:500]}")
        return {
            "success": False,
            "error": "Failed to parse AI response",
            "raw_response": response[:500]
        }
    except Exception as e:
        print(f"[ITINERARY] Error generating itinerary: {e}")
        return {
            "success": False,
            "error": str(e)
        }
