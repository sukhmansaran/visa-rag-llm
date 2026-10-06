"""File upload and storage service."""
import os
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, BinaryIO
from pathlib import Path
import aiofiles
from fastapi import UploadFile, HTTPException, status

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

# Allowed file types
ALLOWED_EXTENSIONS = {
    'image': ['jpg', 'jpeg', 'png', 'gif', 'webp'],
    'document': ['pdf', 'doc', 'docx', 'txt', 'rtf'],
    'all': ['jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt', 'rtf']
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class FileService:
    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR if hasattr(settings, 'UPLOAD_DIR') else 'uploads')
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_extension(self, filename: str) -> str:
        return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    def _validate_file(self, file: UploadFile, allowed_types: str = 'all') -> None:
        ext = self._get_file_extension(file.filename or '')
        allowed = ALLOWED_EXTENSIONS.get(allowed_types, ALLOWED_EXTENSIONS['all'])
        if ext not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type '{ext}' not allowed. Allowed: {', '.join(allowed)}"
            )

    async def _validate_file_size(self, file: UploadFile) -> int:
        content = await file.read()
        size = len(content)
        await file.seek(0)
        if size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        return size

    def _generate_filename(self, original_filename: str, user_id: str) -> str:
        ext = self._get_file_extension(original_filename)
        unique_id = uuid.uuid4().hex[:12]
        timestamp = datetime.utcnow().strftime('%Y%m%d')
        return f"{user_id}/{timestamp}_{unique_id}.{ext}"

    async def upload_file(
        self,
        file: UploadFile,
        user_id: str,
        file_type: str = 'all'
    ) -> dict:
        self._validate_file(file, file_type)
        file_size = await self._validate_file_size(file)
        
        filename = self._generate_filename(file.filename or 'file', user_id)
        file_path = self.upload_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        content = await file.read()
        file_hash = hashlib.md5(content).hexdigest()
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        
        logger.info(f"File uploaded: {filename}, size: {file_size}")
        
        return {
            'filename': filename,
            'original_name': file.filename,
            'size': file_size,
            'content_type': file.content_type,
            'hash': file_hash,
            'url': f"/files/{filename}",
            'uploaded_at': datetime.utcnow().isoformat()
        }

    async def get_file(self, filename: str) -> Optional[Path]:
        file_path = self.upload_dir / filename
        if file_path.exists() and file_path.is_file():
            return file_path
        return None

    async def delete_file(self, filename: str) -> bool:
        file_path = self.upload_dir / filename
        if file_path.exists():
            file_path.unlink()
            logger.info(f"File deleted: {filename}")
            return True
        return False

    def generate_presigned_url(self, filename: str, expires_in: int = 3600) -> str:
        # For local storage, just return the file URL
        # In production with S3/GCS, generate actual presigned URL
        return f"/files/{filename}"


file_service = FileService()
