"""Travel itinerary model for saving generated itineraries."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column
from decimal import Decimal


class TravelItinerary(SQLModel, table=True):
    """User-saved travel itineraries (AI-generated or manual)."""
    
    __tablename__ = "travel_itineraries"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    country: str = Field(index=True, max_length=100)
    duration_days: Optional[int] = Field(default=None)
    budget_tier: Optional[str] = Field(default=None, max_length=20)
    interests: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    generated_by: Optional[str] = Field(default='ai', max_length=20)  # 'ai' or 'manual'
    itinerary_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    destinations_included: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    total_cost_usd: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    visa_info_included: bool = Field(default=False)
    status: str = Field(default='draft', max_length=20)  # draft, confirmed, completed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
