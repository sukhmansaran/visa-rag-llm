"""Travel package management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.travel_package import TravelPackage
from app.api.v1.tourist_visa_schemas import (
    TravelPackageResponse,
    TravelPackageCreate,
    TravelPackageUpdate,
)

router = APIRouter(prefix="/packages", tags=["travel-packages"])


@router.post("/", response_model=TravelPackageResponse)
async def create_package(
    package: TravelPackageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new travel package."""
    db_package = TravelPackage(
        user_id=current_user.id,
        **package.model_dump()
    )
    db.add(db_package)
    await db.commit()
    await db.refresh(db_package)
    return db_package


@router.get("/user", response_model=List[TravelPackageResponse])
async def get_user_packages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all packages for the current user."""
    result = await db.execute(
        select(TravelPackage)
        .where(TravelPackage.user_id == current_user.id)
        .order_by(TravelPackage.created_at.desc())
    )
    packages = result.scalars().all()
    return packages


@router.get("/{package_id}", response_model=TravelPackageResponse)
async def get_package(
    package_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific package by ID."""
    result = await db.execute(
        select(TravelPackage).where(TravelPackage.id == package_id)
    )
    package = result.scalar_one_or_none()
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    if package.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this package")
    
    return package


@router.put("/{package_id}", response_model=TravelPackageResponse)
async def update_package(
    package_id: int,
    package_update: TravelPackageUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a travel package."""
    result = await db.execute(
        select(TravelPackage).where(TravelPackage.id == package_id)
    )
    package = result.scalar_one_or_none()
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    if package.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this package")
    
    # Update fields
    for field, value in package_update.model_dump(exclude_unset=True).items():
        setattr(package, field, value)
    
    await db.commit()
    await db.refresh(package)
    return package


@router.delete("/{package_id}")
async def delete_package(
    package_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a travel package."""
    result = await db.execute(
        select(TravelPackage).where(TravelPackage.id == package_id)
    )
    package = result.scalar_one_or_none()
    
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    
    if package.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this package")
    
    await db.delete(package)
    await db.commit()
    
    return {"message": "Package deleted successfully"}
