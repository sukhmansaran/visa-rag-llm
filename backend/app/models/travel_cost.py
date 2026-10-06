"""Travel cost estimation model."""

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Text
from decimal import Decimal


class TravelCost(SQLModel, table=True):
    """Cost information for travel planning."""
    
    __tablename__ = "travel_costs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    country: str = Field(index=True, max_length=100)
    city: Optional[str] = Field(default=None, index=True, max_length=100)
    category: Optional[str] = Field(default=None, index=True, max_length=50)
    item_name: Optional[str] = Field(default=None, max_length=200)
    cost_usd_min: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    cost_usd_max: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    cost_usd_avg: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    unit: Optional[str] = Field(default=None, max_length=50)
    season: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
