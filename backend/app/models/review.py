from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.user_document import UserDocument


class Review(SQLModel, table=True):
    """Human review tickets for SOPs and documents."""
    
    __tablename__ = "reviews"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    document_id: int = Field(foreign_key="user_documents.id", index=True)
    
    # Status: pending, in_progress, completed, rejected
    status: str = Field(default="pending", max_length=50, index=True)
    
    # Assigned reviewer (admin user)
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id")
    
    # Reviewer comments
    comments: Optional[str] = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = Field(default=None)
    
    # Relationships
    user: "User" = Relationship(
        back_populates="reviews",
        sa_relationship_kwargs={"foreign_keys": "Review.user_id"}
    )
