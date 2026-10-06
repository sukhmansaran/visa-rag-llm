from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.profile import Profile
    from app.models.payment import Payment
    from app.models.watchlist import Watchlist
    from app.models.notification import Notification
    from app.models.user_document import UserDocument
    from app.models.review import Review


class User(SQLModel, table=True):
    """User authentication and account information."""
    
    __tablename__ = "users"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    full_name: Optional[str] = Field(default=None, max_length=255)
    hashed_password: str = Field(max_length=255)
    is_active: bool = Field(default=True)
    is_admin: bool = Field(default=False, index=True)
    is_premium: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    profile: Optional["Profile"] = Relationship(back_populates="user")
    payments: List["Payment"] = Relationship(back_populates="user")
    watchlist: List["Watchlist"] = Relationship(back_populates="user")
    notifications: List["Notification"] = Relationship(back_populates="user")
    documents: List["UserDocument"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[UserDocument.user_id]"}
    )
    reviews: List["Review"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"foreign_keys": "[Review.user_id]"}
    )
