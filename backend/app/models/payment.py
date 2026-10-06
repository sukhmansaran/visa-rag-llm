from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.review import Review


class Payment(SQLModel, table=True):
    """Payment records for Stripe transactions."""
    
    __tablename__ = "payments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Stripe identifiers
    stripe_payment_intent_id: str = Field(unique=True, max_length=255, index=True)
    stripe_customer_id: Optional[str] = Field(default=None, max_length=255)
    
    # Payment details
    amount: int = Field()  # Amount in cents
    currency: str = Field(max_length=3, default="usd")
    status: str = Field(max_length=50, index=True)  # pending, succeeded, failed, refunded
    
    # What was purchased
    product_type: str = Field(max_length=50)  # sop_review, premium_subscription, etc.
    product_id: Optional[int] = Field(default=None)  # ID of related resource (e.g., review_id)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    
    # Relationship
    user: "User" = Relationship(back_populates="payments")
