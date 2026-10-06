"""Travel package model for saving user's travel plans."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column
from decimal import Decimal


class TravelPackage(SQLModel, table=True):
    """User-created travel packages with itinerary and costs."""
    
    __tablename__ = "travel_packages"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    country: str = Field(max_length=100)
    duration_days: Optional[int] = Field(default=None)
    budget_tier: Optional[str] = Field(default=None, max_length=20)
    total_cost_usd: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    itinerary: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    included_destinations: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    cost_breakdown: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
