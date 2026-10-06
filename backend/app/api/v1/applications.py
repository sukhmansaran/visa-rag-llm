from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.application import ApplicationTracker
from app.api.v1.application_schemas import ApplicationTrackerCreate, ApplicationTrackerUpdate, ApplicationTrackerResponse

router = APIRouter(prefix="/applications", tags=["Application Tracker"])

@router.post("", response_model=ApplicationTrackerResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    request: ApplicationTrackerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new application tracking entry."""
    app_entry = ApplicationTracker(
        user_id=current_user.id,
        **request.dict()
    )
    db.add(app_entry)
    await db.commit()
    await db.refresh(app_entry)
    return app_entry

@router.get("", response_model=List[ApplicationTrackerResponse])
async def get_applications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = None,
):
    """Get user's tracked applications."""
    query = select(ApplicationTracker).where(ApplicationTracker.user_id == current_user.id)
    if status:
        query = query.where(ApplicationTracker.status == status)
    
    query = query.order_by(ApplicationTracker.deadline.asc().nulls_last())
    
    result = await db.execute(query)
    apps = result.scalars().all()
    return apps

@router.get("/{app_id}", response_model=ApplicationTrackerResponse)
async def get_application(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific application entry."""
    result = await db.execute(
        select(ApplicationTracker)
        .where(ApplicationTracker.id == app_id)
        .where(ApplicationTracker.user_id == current_user.id)
    )
    app_entry = result.scalar_one_or_none()
    if not app_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return app_entry

@router.patch("/{app_id}", response_model=ApplicationTrackerResponse)
async def update_application(
    app_id: int,
    request: ApplicationTrackerUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an application tracking entry."""
    result = await db.execute(
        select(ApplicationTracker)
        .where(ApplicationTracker.id == app_id)
        .where(ApplicationTracker.user_id == current_user.id)
    )
    app_entry = result.scalar_one_or_none()
    
    if not app_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
        
    update_data = request.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(app_entry, key, value)
        
    app_entry.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(app_entry)
    return app_entry

@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_application(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an application entry."""
    result = await db.execute(
        select(ApplicationTracker)
        .where(ApplicationTracker.id == app_id)
        .where(ApplicationTracker.user_id == current_user.id)
    )
    app_entry = result.scalar_one_or_none()
    
    if not app_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
        
    await db.delete(app_entry)
    await db.commit()
    return None
