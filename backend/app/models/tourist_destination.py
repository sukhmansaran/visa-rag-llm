"""Tourist destination model for travel planning."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column
from sqlalchemy import Text
from decimal import Decimal


class TouristDestination(SQLModel, table=True):
    """Tourist attractions and places to visit."""
    
    __tablename__ = "tourist_destinations"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    country: str = Field(index=True, max_length=100)
    city: str = Field(index=True, max_length=100)
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    category: Optional[str] = Field(default=None, max_length=50)
    rating: Optional[Decimal] = Field(default=None, max_digits=2, decimal_places=1)
    estimated_time: Optional[str] = Field(default=None, max_length=50)
    entry_fee_usd: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    best_time_to_visit: Optional[str] = Field(default=None, max_length=100)
    image_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    coordinates: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
