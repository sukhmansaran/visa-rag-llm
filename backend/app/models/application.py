from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class ApplicationTracker(SQLModel, table=True):
    __tablename__ = "application_trackers"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    university_name: str = Field(index=True)
    program_name: str
    status: str = Field(default="planning") # planning, preparing, submitted, admitted, rejected, waitlisted
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
