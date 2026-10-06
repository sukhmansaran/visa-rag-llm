"""File upload API endpoints."""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import FileResponse
from typing import List

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
    """Upload a single file."""
    result = await file_service.upload_file(file, str(current_user.id), file_type)
    return {"status": "success", "file": result}


@router.post("/upload-multiple")
async def upload_multiple_files(
    files: List[UploadFile] = File(...),
    file_type: str = "all",
    current_user: User = Depends(get_current_user)
):
    """Upload multiple files."""
    results = []
    for f in files[:10]:  # Limit to 10 files
        result = await file_service.upload_file(f, str(current_user.id), file_type)
        results.append(result)
    return {"status": "success", "files": results, "count": len(results)}


@router.get("/{user_id}/{filename}")
async def get_file(
    user_id: str,
    filename: str,
    current_user: User = Depends(get_current_user)
):
    """Get a file by path."""
    # Users can only access their own files (or admin can access all)
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
    """Delete a file."""
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
    if str(current_user.id) != user_id and not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    
    url = file_service.generate_presigned_url(f"{user_id}/{filename}")
    return {"url": url, "expires_in": 3600}
