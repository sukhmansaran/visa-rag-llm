from typing import Optional, Dict, Any
from pydantic import BaseModel


class ProfileResponse(BaseModel):
    """User profile response."""
    id: Optional[int] = None
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    education_level: Optional[str] = None
    field_of_study: Optional[str] = None
    gpa: Optional[float] = None
    test_scores: Optional[Dict[str, Any]] = None
    work_experience: Optional[int] = None
    target_countries: Optional[Dict[str, Any]] = None
    target_universities: Optional[Dict[str, Any]] = None
    notification_preferences: Optional[Dict[str, Any]] = None
    preferred_fields: Optional[list[str]] = None
    intake_periods: Optional[list[str]] = None
    tuition_fee_range: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class ProfileUpdateRequest(BaseModel):
    """Profile update request."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    education_level: Optional[str] = None  # bachelor, master, phd
    field_of_study: Optional[str] = None
    gpa: Optional[float] = None
    test_scores: Optional[Dict[str, Any]] = None  # {gre: {verbal: 160, quant: 170}, toefl: 110}
    work_experience: Optional[int] = None
    target_countries: Optional[Dict[str, Any]] = None
    target_universities: Optional[Dict[str, Any]] = None
    preferred_fields: Optional[list[str]] = None
    intake_periods: Optional[list[str]] = None
    tuition_fee_range: Optional[Dict[str, Any]] = None


class NotificationPreferencesRequest(BaseModel):
    """Notification preferences update."""
    push: bool = True
    email: bool = True
    sms: bool = False
