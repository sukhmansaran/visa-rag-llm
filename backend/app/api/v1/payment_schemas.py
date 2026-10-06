from pydantic import BaseModel, field_serializer
from typing import Optional
from datetime import datetime


class CheckoutRequest(BaseModel):
    """Request to create checkout session."""
    product_type: str  # sop_review, premium_subscription
    product_id: Optional[int] = None  # e.g., document_id for SOP review
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    """Checkout session response."""
    checkout_url: str
    session_id: str


class PaymentResponse(BaseModel):
    """Payment record response."""
    id: int
    amount: int
    currency: str
    status: str
    product_type: str
    created_at: datetime

    @field_serializer('created_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
    
    class Config:
        from_attributes = True
