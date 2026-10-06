"""Tourist visa information model."""

from datetime import datetime
from typing import Optional, Dict, List, Any
from sqlmodel import SQLModel, Field, JSON, Column
from sqlalchemy import Text
from decimal import Decimal


class TouristVisaInfo(SQLModel, table=True):
    """Visa requirements and application process for tourist visas."""
    
    __tablename__ = "tourist_visa_info"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    country: str = Field(unique=True, index=True, max_length=100)
    visa_required: bool = Field(default=True)
    visa_types: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    processing_time: Optional[str] = Field(default=None, max_length=100)
    validity_period: Optional[str] = Field(default=None, max_length=100)
    visa_fee_usd: Optional[Decimal] = Field(default=None, max_digits=10, decimal_places=2)
    requirements: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    application_process: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    interview_required: Optional[bool] = Field(default=None)
    online_application: Optional[bool] = Field(default=None)
    official_website: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
