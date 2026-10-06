from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ApplicationTrackerCreate(BaseModel):
    university_name: str
    program_name: str
    status: str = "planning"
    deadline: Optional[datetime] = None
    notes: Optional[str] = None

class ApplicationTrackerUpdate(BaseModel):
    university_name: Optional[str] = None
    program_name: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None

class ApplicationTrackerResponse(BaseModel):
    id: int
    user_id: int
    university_name: str
    program_name: str
    status: str
    deadline: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
