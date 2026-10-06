from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, JSON, Column

if TYPE_CHECKING:
    from app.models.user import User


class Profile(SQLModel, table=True):
    """User profile with educational background and preferences."""
    
    __tablename__ = "profiles"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", unique=True, index=True)
    
    # Personal info
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    
    # Education
    education_level: Optional[str] = Field(default=None, max_length=50)  # bachelor, master, phd
    field_of_study: Optional[str] = Field(default=None, max_length=200)
    gpa: Optional[float] = Field(default=None)
    
    # Test scores (JSON: {gre: {verbal: 160, quant: 170}, toefl: 110})
    test_scores: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    # Work experience (years)
    work_experience: Optional[int] = Field(default=None)
    
    # Target countries and universities (JSON arrays)
    target_countries: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    target_universities: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    # Preference fields
    preferred_fields: Optional[list] = Field(default=None, sa_column=Column(JSON))
    intake_periods: Optional[list] = Field(default=None, sa_column=Column(JSON))
    tuition_fee_range: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    # Notification preferences (JSON)
    notification_preferences: Optional[Dict[str, Any]] = Field(
        default={"push": True, "email": True, "sms": False},
        sa_column=Column(JSON)
    )
    
    # Relationships
    user: "User" = Relationship(back_populates="profile")
