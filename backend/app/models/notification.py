from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User


class Notification(SQLModel, table=True):
    """User notifications for changes, updates, and alerts."""
    
    __tablename__ = "notifications"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    title: str = Field(max_length=255)
    message: str = Field()
    
    # Type: change_alert, reminder, system, review_complete
    notification_type: str = Field(max_length=50, index=True)
    
    # Related URL (source that changed, etc.)
    related_url: Optional[str] = Field(default=None, max_length=2048)
    
    is_read: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationships
    user: "User" = Relationship(back_populates="notifications")
