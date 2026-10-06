"""
Tourist context service.
Fetches verified tourist visa details, destinations, and travel cost ranges from the PostgreSQL database.
"""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.tourist_visa_info import TouristVisaInfo
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost


async def get_tourist_context(db: Optional[AsyncSession], query: str, country: Optional[str] = None) -> str:
    """
    Fetch relevant tourist information from database based on query.
    
    Args:
        db: Database session
        query: User's query
        country: Optional country to focus on
        
    Returns:
        Formatted context string with relevant tourist data
    """
    if not db:
        return ""

    context_parts: List[str] = []
    query_lower = query.lower()
    
    # Detect country from query if not provided
    if not country:
        common_countries = ['usa', 'uk', 'thailand', 'france', 'japan', 'canada', 'australia']
        for c in common_countries:
            if c in query_lower:
                country = c.upper() if c != 'uk' else 'UK'
                break
    
    try:
        # 1. Fetch visa information if query mentions visa
        if 'visa' in query_lower and country:
            result = await db.execute(
                select(TouristVisaInfo).where(TouristVisaInfo.country == country)
            )
            visa_info = result.scalar_one_or_none()
            
            if visa_info:
                context_parts.append(f"\nVISA INFORMATION FOR {country}:")
                context_parts.append(f"- Visa Required: {'Yes' if visa_info.visa_required else 'No'}")
                if visa_info.visa_types:
                    types_str = ', '.join(visa_info.visa_types) if isinstance(visa_info.visa_types, list) else str(visa_info.visa_types)
                    context_parts.append(f"- Visa Types: {types_str}")
                if visa_info.processing_time:
                    context_parts.append(f"- Processing Time: {visa_info.processing_time}")
                if visa_info.visa_fee_usd:
                    context_parts.append(f"- Visa Fee: ${visa_info.visa_fee_usd}")
                if visa_info.requirements:
                    reqs = visa_info.requirements if isinstance(visa_info.requirements, list) else []
                    if reqs:
                        context_parts.append(f"- Requirements: {', '.join(reqs[:5])}")
        
        # 2. Fetch destinations if query mentions attractions/places/visit
        if any(word in query_lower for word in ['attraction', 'place', 'visit', 'see', 'destination', 'tourist']) and country:
            result = await db.execute(
                select(TouristDestination)
                .where(TouristDestination.country == country)
                .order_by(TouristDestination.rating.desc())
                .limit(5)
            )
            destinations = result.scalars().all()
            
            if destinations:
                context_parts.append(f"\nTOP DESTINATIONS IN {country}:")
                for dest in destinations:
                    desc = dest.description[:100] if dest.description else 'No description'
                    context_parts.append(f"- {dest.name} ({dest.city}): {desc}... Rating: {dest.rating}/5")
                    if dest.entry_fee_usd:
                        context_parts.append(f"  Entry Fee: ${dest.entry_fee_usd}")
        
        # 3. Fetch cost information if query mentions cost/price/budget
        if any(word in query_lower for word in ['cost', 'price', 'budget', 'expensive', 'cheap', 'afford']) and country:
            result = await db.execute(
                select(TravelCost)
                .where(TravelCost.country == country)
                .limit(10)
            )
            costs = result.scalars().all()
            
            if costs:
                context_parts.append(f"\nCOST INFORMATION FOR {country}:")
                cost_by_category = {}
                for cost in costs:
                    if cost.category not in cost_by_category:
                        cost_by_category[cost.category] = []
                    cost_by_category[cost.category].append(cost)
                
                for category, items in cost_by_category.items():
                    if items:
                        avg_cost = sum(c.cost_usd_avg for c in items if c.cost_usd_avg) / len(items)
                        unit = items[0].unit if items[0].unit else ''
                        context_parts.append(f"- {category.capitalize()}: ~${avg_cost:.2f} {unit}")
        
    except Exception as e:
        print(f"[TOURIST_SERVICE] Error fetching tourist context: {e}")
    
    return "\n".join(context_parts) if context_parts else ""
