from typing import Optional
from datetime import datetime
from pydantic import BaseModel, field_serializer


class WatchlistAddRequest(BaseModel):
    """Request to add item to watchlist."""
    watched_type: str  # country, university, visa_type
    watched_value: str  # e.g., "Canada", "University of Toronto"


class WatchlistResponse(BaseModel):
    """Watchlist item response."""
    id: int
    watched_type: str
    watched_value: str
    created_at: datetime

    @field_serializer('created_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
    
    class Config:
        from_attributes = True
