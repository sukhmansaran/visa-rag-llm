from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user, get_current_admin_user
from app.models.user import User
from app.models.review import Review
from app.models.user_document import UserDocument
from app.api.v1.review_schemas import (
    ReviewRequest,
    ReviewResponse,
    ReviewUpdateRequest,
)


router = APIRouter(prefix="/reviews", tags=["Reviews"])


@router.post("/request", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def request_review(
    request: ReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Request expert review for a document.
    
    Note: User must have paid for review (payment verified via webhook).
    """
    # Verify document exists and belongs to user
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == request.document_id)
        .where(UserDocument.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Check if review already exists
    result = await db.execute(
        select(Review)
        .where(Review.document_id == request.document_id)
        .where(Review.status.in_(["pending", "in_progress"]))
    )
    existing_review = result.scalar_one_or_none()
    
    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Review already pending for this document"
        )
    
    # Create review (payment handled separately via webhooks)
    review = Review(
        user_id=current_user.id,
        document_id=request.document_id,
        status="pending",
        reviewer_notes=request.notes,
    )
    
    db.add(review)
    await db.commit()
    await db.refresh(review)
    
    return review


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get review status."""
    
    result = await db.execute(
        select(Review)
        .where(Review.id == review_id)
        .where(Review.user_id == current_user.id)
    )
    review = result.scalar_one_or_none()
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )
    
    return review


@router.get("", response_model=list[ReviewResponse])
async def list_user_reviews(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all reviews for current user."""
    
    result = await db.execute(
        select(Review)
        .where(Review.user_id == current_user.id)
        .order_by(desc(Review.created_at))
    )
    reviews = result.scalars().all()
    
    return reviews


# Admin endpoints
@router.get("/admin/queue", response_model=list[ReviewResponse])
async def get_review_queue(
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = None,
):
    """
    Get review queue (admin only).
    
    Returns all pending and in-progress reviews.
    """
    query = select(Review)
    
    if status_filter:
        query = query.where(Review.status == status_filter)
    else:
        query = query.where(Review.status.in_(["pending", "in_progress"]))
    
    query = query.order_by(Review.created_at)
    
    result = await db.execute(query)
    reviews = result.scalars().all()
    
    return reviews


@router.put("/admin/{review_id}", response_model=ReviewResponse)
async def update_review(
    review_id: int,
    request: ReviewUpdateRequest,
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update review status and add comments (admin only).
    """
    result = await db.execute(
        select(Review).where(Review.id == review_id)
    )
    review = result.scalar_one_or_none()
    
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )
    
    # Update review
    review.status = request.status
    if request.comments:
        review.reviewer_comments = request.comments
    
    review.reviewer_id = current_user.id
    
    if request.status == "completed":
        review.reviewed_at = datetime.utcnow()
        
        # Mark document as reviewed
        result = await db.execute(
            select(UserDocument).where(UserDocument.id == review.document_id)
        )
        document = result.scalar_one_or_none()
        if document:
            document.is_reviewed = True
            document.reviewed_by = current_user.id
            document.reviewed_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(review)
    
    return review
