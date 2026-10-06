from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime
import logging

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.profile import Profile
from app.models.user_document import UserDocument
from app.api.v1.document_schemas import (
    SOPGenerateRequest,
    SOPResponse,
    SOPUpdateRequest,
    DocumentListResponse,
)
from app.services.sop_generator import generate_sop

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

@router.post("/sop/generate", response_model=SOPResponse, status_code=status.HTTP_201_CREATED)
async def generate_sop_endpoint(
    request: SOPGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate SOP draft using LLM and user profile."""
    try:
        logger.info("Starting SOP generation", extra={"user_id": current_user.id, "university": request.university, "program": request.program})
        
        # Get user profile
        result = await db.execute(
            select(Profile).where(Profile.user_id == current_user.id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            logger.warning("Profile not found for SOP generation", extra={"user_id": current_user.id})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile not found. Please complete your profile first.",
            )
        
        # Generate SOP
        sop_content = await generate_sop(
            profile=profile,
            university=request.university,
            program=request.program,
            additional_info=request.additional_info,
        )
        
        logger.info("SOP generated successfully", extra={"user_id": current_user.id, "length": len(sop_content)})
        
        # Save to database
        document = UserDocument(
            user_id=current_user.id,
            document_type="sop",
            content=sop_content,
            version=1,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        
        logger.info("SOP document saved", extra={"user_id": current_user.id, "document_id": document.id})
        
        # Convert datetime objects to strings for response
        response_data = {
            "id": document.id,
            "document_type": document.document_type,
            "content": document.content,
            "version": document.version,
            "is_reviewed": document.is_reviewed,
            "reviewed_by": document.reviewed_by,
            "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
            "created_at": document.created_at.isoformat(),
            "updated_at": document.updated_at.isoformat(),
        }
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error generating SOP", extra={"user_id": current_user.id, "error": str(e)}, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate SOP: {str(e)}",
        )

@router.get("/sop/{document_id}", response_model=SOPResponse)
async def get_sop(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific SOP document."""
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == document_id)
        .where(UserDocument.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
        
    # Convert datetime objects to strings
    return {
        "id": document.id,
        "document_type": document.document_type,
        "content": document.content,
        "version": document.version,
        "is_reviewed": document.is_reviewed,
        "reviewed_by": document.reviewed_by,
        "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }

@router.put("/sop/{document_id}", response_model=SOPResponse)
async def update_sop(
    document_id: int,
    request: SOPUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update SOP content (save edits)."""
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == document_id)
        .where(UserDocument.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    document.content = request.content
    document.version += 1
    document.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(document)
    
    # Convert datetime objects to strings
    return {
        "id": document.id,
        "document_type": document.document_type,
        "content": document.content,
        "version": document.version,
        "is_reviewed": document.is_reviewed,
        "reviewed_by": document.reviewed_by,
        "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }

@router.get("/", response_model=list[DocumentListResponse])
async def list_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    document_type: Optional[str] = None,
):
    """List all user documents."""
    query = select(UserDocument).where(UserDocument.user_id == current_user.id)
    if document_type:
        query = query.where(UserDocument.document_type == document_type)
    query = query.order_by(desc(UserDocument.created_at))
    result = await db.execute(query)
    documents = result.scalars().all()
    
    # Convert datetime objects to strings
    response_list = []
    for doc in documents:
        response_list.append({
            "id": doc.id,
            "document_type": doc.document_type,
            "version": doc.version,
            "is_reviewed": doc.is_reviewed,
            "created_at": doc.created_at.isoformat(),
        })
    
    return response_list

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    result = await db.execute(
        select(UserDocument)
        .where(UserDocument.id == document_id)
        .where(UserDocument.user_id == current_user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    await db.delete(document)
    await db.commit()
    return None
