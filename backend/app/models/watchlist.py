from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User


class Watchlist(SQLModel, table=True):
    """User subscriptions to universities, countries, or visa types for change notifications."""
    
    __tablename__ = "watchlist"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Type: country, university, visa_type
    watched_type: str = Field(max_length=50, index=True)
    
    # Value: e.g., "UK", "University of Oxford", "F-1 Visa"
    watched_value: str = Field(max_length=255, index=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    user: "User" = Relationship(back_populates="watchlist")
