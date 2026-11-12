"""
Admin review queue for live-fetched pages (M5.5b, D2; the page for it is M6.5).

A fetched registry page that differs from the stored copy waits here. Approving backs up the database and the
knowledge base, then ingests exactly the reviewed text; rejecting deletes it. Admin-only.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_admin_user
from app.models.user import User
from app.services import review_queue

router = APIRouter(prefix="/admin/review-queue", tags=["Admin"], dependencies=[Depends(get_current_admin_user)])


def _refused(error: review_queue.ReviewError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


@router.get("")
async def list_review_items(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query("pending", pattern="^(pending|approved|rejected|all)$"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetched pages waiting for review (or already reviewed), newest first. No page text in the list."""
    return {"items": await review_queue.list_items(db, None if status == "all" else status, limit)}


@router.get("/{item_id}")
async def get_review_item(item_id: int, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """One item: the fetched text, the stored copy and their diff."""
    try:
        return await review_queue.detail(db, item_id)
    except review_queue.ReviewError as e:
        raise _refused(e)


@router.post("/{item_id}/approve")
async def approve_review_item(item_id: int, db: AsyncSession = Depends(get_db),
                              admin: User = Depends(get_current_admin_user)) -> Dict[str, Any]:
    """Back up, then make the reviewed text the page's stored version."""
    try:
        return await review_queue.approve(db, item_id, reviewer_id=admin.id)
    except review_queue.ReviewError as e:
        raise _refused(e)


@router.post("/{item_id}/reject")
async def reject_review_item(item_id: int, db: AsyncSession = Depends(get_db),
                             admin: User = Depends(get_current_admin_user)) -> Dict[str, Any]:
    """Delete the fetched text; the knowledge base is unchanged."""
    try:
        return await review_queue.reject(db, item_id, reviewer_id=admin.id)
    except review_queue.ReviewError as e:
        raise _refused(e)
