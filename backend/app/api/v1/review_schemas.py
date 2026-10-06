from pydantic import BaseModel, field_serializer
from typing import Optional
from datetime import datetime


class ReviewRequest(BaseModel):
    """Request to create a review."""
    document_id: int
    notes: Optional[str] = None


class ReviewResponse(BaseModel):
    """Review response."""
    id: int
    document_id: int
    status: str
    reviewer_id: Optional[int] = None
    payment_id: Optional[int] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    @field_serializer('created_at', 'reviewed_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
    
    class Config:
        from_attributes = True


class ReviewUpdateRequest(BaseModel):
    """Admin request to update review."""
    status: str  # pending, in_progress, completed, rejected
    comments: Optional[str] = None
