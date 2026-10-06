"""
Device registration endpoints for push notifications.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User


router = APIRouter(prefix="/devices", tags=["Devices"])


class DeviceRegistrationRequest(BaseModel):
    """Device registration request."""
    fcm_token: str
    device_type: str  # ios, android, web
    device_name: str = ""


class DeviceRegistrationResponse(BaseModel):
    """Device registration response."""
    message: str
    device_type: str


@router.post("/register", response_model=DeviceRegistrationResponse)
async def register_device(
    request: DeviceRegistrationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register device for push notifications.
    
    Stores FCM token for the user.
    """
    
    # For now, store in user metadata
    # In production, create a separate Device model
    if not hasattr(current_user, 'fcm_tokens'):
        current_user.fcm_tokens = []
    
    # Add token if not already present
    if request.fcm_token not in (current_user.fcm_tokens or []):
        if current_user.fcm_tokens is None:
            current_user.fcm_tokens = []
        current_user.fcm_tokens.append(request.fcm_token)
        
        await db.commit()
    
    return DeviceRegistrationResponse(
        message="Device registered successfully",
        device_type=request.device_type
    )


@router.delete("/unregister")
async def unregister_device(
    fcm_token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Unregister device from push notifications.
    """
    
    if hasattr(current_user, 'fcm_tokens') and current_user.fcm_tokens:
        if fcm_token in current_user.fcm_tokens:
            current_user.fcm_tokens.remove(fcm_token)
            await db.commit()
    
    return {"message": "Device unregistered successfully"}
