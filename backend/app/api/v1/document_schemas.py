from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_serializer


class SOPGenerateRequest(BaseModel):
    """Request to generate SOP."""
    university: str
    program: str
    additional_info: Optional[str] = None


class SOPResponse(BaseModel):
    """SOP document response."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    document_type: str
    content: str
    version: int
    is_reviewed: bool
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[str] = None
    created_at: str
    updated_at: str


class SOPUpdateRequest(BaseModel):
    """Request to update SOP content."""
    content: str


class DocumentListResponse(BaseModel):
    """List of user documents."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    document_type: str
    version: int
    is_reviewed: bool
    created_at: str
