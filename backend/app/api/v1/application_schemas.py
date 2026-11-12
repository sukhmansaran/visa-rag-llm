from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# The stages the tracker page offers (M6.4); anything else is refused rather than stored
ApplicationStatus = Literal["planning", "preparing", "submitted", "admitted", "rejected", "waitlisted"]
Name = Field(min_length=1, max_length=200)
Notes = Field(default=None, max_length=2000)


class ApplicationTrackerCreate(BaseModel):
    university_name: str = Name
    program_name: str = Name
    status: ApplicationStatus = "planning"
    deadline: Optional[datetime] = None
    notes: Optional[str] = Notes


class ApplicationTrackerUpdate(BaseModel):
    university_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    program_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[ApplicationStatus] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = Notes


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
