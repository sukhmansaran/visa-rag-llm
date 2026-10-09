"""File upload and document ingestion API endpoints."""
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.security import get_current_user
from app.models.user import User
from app.services.file_service import file_service
from app.core.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = "all",
    current_user: User = Depends(get_current_user)
):
    """
    Upload and securely store a single file.
    Enforces magic-byte verification, max size of 10MB, and strips metadata.
    """
    result = await file_service.upload_file(file, str(current_user.id), file_type)
    return {"status": "success", "file": result}


@router.post("/upload-multiple")
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    file_type: str = "all",
    current_user: User = Depends(get_current_user)
):
    """Upload multiple files (up to 10 files per request)."""
    if len(files) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch upload exceeds limit of 10 files."
        )

    results = []
    for f in files:
        result = await file_service.upload_file(f, str(current_user.id), file_type)
        results.append(result)
    return {"status": "success", "files": results, "count": len(results)}


@router.post("/sanitize")
async def sanitize_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Upload and sanitize an applicant document (PDF).
    Extracts text, strips comments/metadata, and neutralizes prompt injection payloads.
    """
    result = await file_service.extract_and_sanitize_document(file, str(current_user.id))
    return {"status": "success", "data": result}


@router.get("/{user_id}/{filename}")
async def get_file(
    user_id: str,
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Get a file by path with ownership verification."""
    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

    if str(current_user.id) != user_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    file_path = await file_service.get_file(f"{user_id}/{filename}")
    if not file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    return FileResponse(file_path)


@router.delete("/{user_id}/{filename}")
async def delete_file(
    user_id: str,
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Delete a file with ownership verification."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

    if str(current_user.id) != user_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    deleted = await file_service.delete_file(f"{user_id}/{filename}")
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    return {"status": "success", "message": "File deleted"}


@router.get("/presigned-url/{user_id}/{filename}")
async def get_presigned_url(
    user_id: str,
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Get a presigned URL for file access."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

    if str(current_user.id) != user_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    url = file_service.generate_presigned_url(f"{user_id}/{filename}")
    return {"url": url, "expires_in": 3600}
