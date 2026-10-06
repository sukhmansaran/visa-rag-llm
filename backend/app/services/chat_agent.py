"""
Chat agent using Google Gemini API directly (bypassing LangChain for simplicity).
Enhanced with tourist visa database integration and streaming support.
"""

from typing import TypedDict, Annotated, Sequence, Optional, Dict, Any, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.llm import llm_service
from app.core.config import settings
from app.models.tourist_visa_info import TouristVisaInfo
from app.models.tourist_destination import TouristDestination
from app.models.travel_cost import TravelCost


# System prompt for the visa assistant
SYSTEM_PROMPT = """You are Pendu, an AI-powered visa and travel assistant. 
You help users with:

STUDY ABROAD:
- Student visa application processes and requirements for different countries
- University admissions and requirements
- Document checklists and preparation
- Statement of Purpose (SOP) guidance
- General study abroad advice

TOURIST VISA & TRAVEL:
- Tourist visa requirements and application processes by country
- Travel planning and destination recommendations
- Cost estimation for trips (flights, hotels, food, activities)
- Itinerary suggestions based on budget and interests
- Popular tourist attractions and places to visit
- Best time to visit different destinations
- Travel tips, local culture, and safety information

Guidelines:
- Be helpful, accurate, and concise
- For visa requirements, provide detailed step-by-step guidance
- For travel planning, consider the user's budget and preferences
- When estimating costs, provide realistic ranges (budget/mid-range/luxury)
- Suggest popular destinations and hidden gems
- If you're unsure about specific requirements, recommend users verify with official embassy or tourism websites
- Always be encouraging and supportive
- Ask clarifying questions if the user's query is ambiguous

Remember: You are a knowledgeable assistant for both study abroad AND tourist travel, but always recommend verifying critical information with official sources."""


async def generate_chat_response_stream(
    query: str,
    country: str | None = None,
    university: str | None = None,
    chat_history: list[dict] | None = None,
    db: Optional[AsyncSession] = None,
) -> AsyncGenerator[str, None]:
    """
    Generate a streaming chat response using Google Gemini.
    
    Args:
        query: User's question
        country: Optional country context
        university: Optional university context
        chat_history: Optional list of previous messages
        db: Optional database session for querying tourist data
        
    Yields:
        Text chunks as they are generated
    """
    
    print(f"[CHAT STREAM] Generating streaming response for query: {query[:50]}...")
    
    # Build context (same as non-streaming version)
    context_parts = []
    
    if country:
        context_parts.append(f"User is interested in: {country}")
    if university:
        context_parts.append(f"University of interest: {university}")
    
    # Query tourist database if relevant
    tourist_context = ""
    if db and any(keyword in query.lower() for keyword in [
        'visa', 'travel', 'visit', 'tourist', 'destination', 'cost', 'trip', 
        'vacation', 'holiday', 'attraction', 'hotel', 'flight', 'budget'
    ]):
        print(f"[CHAT STREAM] Detected tourist query, fetching database context...")
        tourist_context = await _get_tourist_context(db, query, country)
        if tourist_context:
            context_parts.append("\n=== TOURIST INFORMATION FROM DATABASE ===")
            context_parts.append(tourist_context)
            context_parts.append("=== END DATABASE INFORMATION ===\n")
    
    # Add recent chat history
    if chat_history:
        context_parts.append("\nRecent conversation:")
        for msg in chat_history[-5:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            context_parts.append(f"{role.capitalize()}: {content}")
    
    context = "\n".join(context_parts) if context_parts else ""
    
    print(f"[CHAT STREAM] Context length: {len(context)} chars")
    if tourist_context:
        print(f"[CHAT STREAM] ✓ Added tourist database context")
    
    try:
        # Stream response from Gemini
        async for chunk in llm_service.generate_answer_stream(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=query,
            context=context,
            temperature=0.7,
            max_tokens=1500,
        ):
            yield chunk
        
        print(f"[CHAT STREAM] ✓ Stream completed")
        
    except Exception as e:
        print(f"[CHAT STREAM] ✗ Error generating response: {e}")
        yield "I'm sorry, I encountered an error processing your request. Please try again."


async def generate_chat_response(
    query: str,
    country: str | None = None,
    university: str | None = None,
    chat_history: list[dict] | None = None,
    db: Optional[AsyncSession] = None,
) -> str:
    """
    Generate a chat response using Google Gemini with tourist database integration.
    
    Args:
        query: User's question
        country: Optional country context
        university: Optional university context
        chat_history: Optional list of previous messages
        db: Optional database session for querying tourist data
        
    Returns:
        AI response text
    """
    
    print(f"[CHAT] Generating response for query: {query[:50]}...")
    
    # Build context from chat history
    context_parts = []
    
    # Add country/university context if provided
    if country:
        context_parts.append(f"User is interested in: {country}")
    if university:
        context_parts.append(f"University of interest: {university}")
    
    # Query tourist database if relevant and db session provided
    tourist_context = ""
    if db and any(keyword in query.lower() for keyword in [
        'visa', 'travel', 'visit', 'tourist', 'destination', 'cost', 'trip', 
        'vacation', 'holiday', 'attraction', 'hotel', 'flight', 'budget'
    ]):
        print(f"[CHAT] Detected tourist query, fetching database context...")
        tourist_context = await _get_tourist_context(db, query, country)
        if tourist_context:
            context_parts.append("\n=== TOURIST INFORMATION FROM DATABASE ===")
            context_parts.append(tourist_context)
            context_parts.append("=== END DATABASE INFORMATION ===\n")
    
    # Add recent chat history for context
    if chat_history:
        context_parts.append("\nRecent conversation:")
        for msg in chat_history[-5:]:  # Last 5 messages for context
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            context_parts.append(f"{role.capitalize()}: {content}")
    
    context = "\n".join(context_parts) if context_parts else ""
    
    print(f"[CHAT] Context length: {len(context)} chars")
    if tourist_context:
        print(f"[CHAT] ✓ Added tourist database context")
    
    try:
        # Use Gemini service to generate response
        response = await llm_service.generate_answer(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=query,
            context=context,
            temperature=0.7,
            max_tokens=1500,
        )
        
        print(f"[CHAT] ✓ Response generated ({len(response)} chars)")
        return response
        
    except Exception as e:
        print(f"[CHAT] ✗ Error generating response: {e}")
        return "I'm sorry, I encountered an error processing your request. Please try again."


async def _get_tourist_context(db: AsyncSession, query: str, country: Optional[str] = None) -> str:
    """
    Fetch relevant tourist information from database based on query.
    
    Args:
        db: Database session
        query: User's query
        country: Optional country to focus on
        
    Returns:
        Formatted context string with relevant tourist data
    """
    context_parts = []
    query_lower = query.lower()
    
    # Detect country from query if not provided
    if not country:
        # Simple country detection (can be improved)
        common_countries = ['usa', 'uk', 'thailand', 'france', 'japan', 'canada', 'australia']
        for c in common_countries:
            if c in query_lower:
                country = c.upper() if c != 'uk' else 'UK'
                break
    
    try:
        # Fetch visa information if query mentions visa
        if 'visa' in query_lower and country:
            result = await db.execute(
                select(TouristVisaInfo).where(TouristVisaInfo.country == country)
            )
            visa_info = result.scalar_one_or_none()
            
            if visa_info:
                context_parts.append(f"\nVISA INFORMATION FOR {country}:")
                context_parts.append(f"- Visa Required: {'Yes' if visa_info.visa_required else 'No'}")
                if visa_info.visa_types:
                    context_parts.append(f"- Visa Types: {', '.join(visa_info.visa_types) if isinstance(visa_info.visa_types, list) else visa_info.visa_types}")
                if visa_info.processing_time:
                    context_parts.append(f"- Processing Time: {visa_info.processing_time}")
                if visa_info.visa_fee_usd:
                    context_parts.append(f"- Visa Fee: ${visa_info.visa_fee_usd}")
                if visa_info.requirements:
                    reqs = visa_info.requirements if isinstance(visa_info.requirements, list) else []
                    if reqs:
                        context_parts.append(f"- Requirements: {', '.join(reqs[:5])}")
        
        # Fetch destinations if query mentions attractions/places/visit
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
                    context_parts.append(f"- {dest.name} ({dest.city}): {dest.description[:100] if dest.description else 'No description'}... Rating: {dest.rating}/5")
                    if dest.entry_fee_usd:
                        context_parts.append(f"  Entry Fee: ${dest.entry_fee_usd}")
        
        # Fetch cost information if query mentions cost/price/budget
        if any(word in query_lower for word in ['cost', 'price', 'budget', 'expensive', 'cheap', 'afford']) and country:
            result = await db.execute(
                select(TravelCost)
                .where(TravelCost.country == country)
                .limit(10)
            )
            costs = result.scalars().all()
            
            if costs:
                context_parts.append(f"\nCOST INFORMATION FOR {country}:")
                
                # Group by category
                cost_by_category = {}
                for cost in costs:
                    if cost.category not in cost_by_category:
                        cost_by_category[cost.category] = []
                    cost_by_category[cost.category].append(cost)
                
                for category, items in cost_by_category.items():
                    if items:
                        avg_cost = sum(c.cost_usd_avg for c in items if c.cost_usd_avg) / len(items)
                        context_parts.append(f"- {category.capitalize()}: ~${avg_cost:.2f} {items[0].unit if items[0].unit else ''}")
        
    except Exception as e:
        print(f"[CHAT] Error fetching tourist context: {e}")
    
    return "\n".join(context_parts) if context_parts else ""
