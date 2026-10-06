from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.user import User


class UserDocument(SQLModel, table=True):
    """User-generated documents: SOPs, essays, resumes, etc."""
    
    __tablename__ = "user_documents"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Type: sop, lor, resume, essay, other
    document_type: str = Field(max_length=50, index=True)
    
    # Document content (text)
    content: str = Field()
    
    # Version tracking
    version: int = Field(default=1)
    
    # Review status
    is_reviewed: bool = Field(default=False)
    reviewed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)
    
    # Storage URL (for uploaded files)
    storage_url: Optional[str] = Field(default=None, max_length=2048)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    user: "User" = Relationship(
        back_populates="documents",
        sa_relationship_kwargs={"foreign_keys": "[UserDocument.user_id]"}
    )
