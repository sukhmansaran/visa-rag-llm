from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_serializer


class SignupRequest(BaseModel):
    """Signup request schema."""
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """Login request schema."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User response schema."""
    id: int
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_admin: bool
    is_premium: bool = False
    created_at: datetime

    @field_serializer('created_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Refresh token request schema."""
    refresh_token: str
