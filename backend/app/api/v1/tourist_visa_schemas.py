"""Pydantic schemas for tourist visa endpoints."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


# Tourist Visa Info Schemas
class TouristVisaInfoBase(BaseModel):
    country: str
    visa_required: bool = True
    visa_types: Optional[List[str]] = None
    processing_time: Optional[str] = None
    validity_period: Optional[str] = None
    visa_fee_usd: Optional[Decimal] = None
    requirements: Optional[List[str]] = None
    application_process: Optional[List[Dict[str, Any]]] = None  # Changed to Any to accept int or str
    interview_required: Optional[bool] = None
    online_application: Optional[bool] = None
    official_website: Optional[str] = None


class TouristVisaInfoCreate(TouristVisaInfoBase):
    pass


class TouristVisaInfoResponse(TouristVisaInfoBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Tourist Destination Schemas
class TouristDestinationBase(BaseModel):
    country: str
    city: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    rating: Optional[Decimal] = None
    estimated_time: Optional[str] = None
    entry_fee_usd: Optional[Decimal] = None
    best_time_to_visit: Optional[str] = None
    image_url: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None


class TouristDestinationCreate(TouristDestinationBase):
    pass


class TouristDestinationResponse(TouristDestinationBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


# Travel Cost Schemas
class TravelCostBase(BaseModel):
    country: str
    city: Optional[str] = None
    category: Optional[str] = None
    item_name: Optional[str] = None
    cost_usd_min: Optional[Decimal] = None
    cost_usd_max: Optional[Decimal] = None
    cost_usd_avg: Optional[Decimal] = None
    unit: Optional[str] = None
    season: Optional[str] = None
    notes: Optional[str] = None


class TravelCostCreate(TravelCostBase):
    pass


class TravelCostResponse(TravelCostBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CostEstimateRequest(BaseModel):
    country: str
    duration_days: int = Field(gt=0, le=365)
    budget_tier: str = Field(pattern="^(budget|mid-range|luxury)$")
    travelers: int = Field(default=1, gt=0, le=20)
    cities: Optional[List[str]] = None


class CostBreakdown(BaseModel):
    category: str
    cost_usd: Decimal
    details: str


class CostEstimateResponse(BaseModel):
    country: str
    duration_days: int
    budget_tier: str
    travelers: int
    total_cost_usd: Decimal
    per_person_cost_usd: Decimal
    breakdown: List[CostBreakdown]


# Travel Package Schemas
class TravelPackageBase(BaseModel):
    country: str
    duration_days: Optional[int] = None
    budget_tier: Optional[str] = None
    total_cost_usd: Optional[Decimal] = None
    itinerary: Optional[Dict[str, Any]] = None
    included_destinations: Optional[List[int]] = None
    cost_breakdown: Optional[Dict[str, Any]] = None


class TravelPackageCreate(TravelPackageBase):
    pass


class TravelPackageUpdate(BaseModel):
    duration_days: Optional[int] = None
    budget_tier: Optional[str] = None
    total_cost_usd: Optional[Decimal] = None
    itinerary: Optional[Dict[str, Any]] = None
    included_destinations: Optional[List[int]] = None
    cost_breakdown: Optional[Dict[str, Any]] = None


class TravelPackageResponse(TravelPackageBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
