from datetime import datetime
from typing import Optional
import re

from pydantic import BaseModel, EmailStr, Field, field_serializer, field_validator


PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128


class SignupRequest(BaseModel):
    """Signup request schema with a minimum password policy (A4)."""
    email: EmailStr
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain at least one letter and one number")
        if len(set(v)) < 4:
            raise ValueError("Password is too repetitive")
        return v


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
