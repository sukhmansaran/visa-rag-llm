from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.watchlist import Watchlist
from app.api.v1.watchlist_schemas import WatchlistAddRequest, WatchlistResponse

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])

@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def add_to_watchlist(
    request: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add item to user's watchlist."""
    # Check if already exists
    result = await db.execute(
        select(Watchlist)
        .where(Watchlist.user_id == current_user.id)
        .where(Watchlist.watched_type == request.watched_type)
        .where(Watchlist.watched_value == request.watched_value)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Item already in watchlist",
        )
    # Create new watchlist item
    watchlist_item = Watchlist(
        user_id=current_user.id,
        watched_type=request.watched_type,
        watched_value=request.watched_value,
    )
    db.add(watchlist_item)
    await db.commit()
    await db.refresh(watchlist_item)
    return watchlist_item

@router.get("", response_model=list[WatchlistResponse])
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    watched_type: Optional[str] = None,
):
    """Get user's watchlist items."""
    query = select(Watchlist).where(Watchlist.user_id == current_user.id)
    if watched_type:
        query = query.where(Watchlist.watched_type == watched_type)
    query = query.order_by(desc(Watchlist.created_at))
    result = await db.execute(query)
    items = result.scalars().all()
    return items

@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(
    watchlist_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove item from watchlist."""
    result = await db.execute(
        select(Watchlist)
        .where(Watchlist.id == watchlist_id)
        .where(Watchlist.user_id == current_user.id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found",
        )
    await db.delete(item)
    await db.commit()
    return None
