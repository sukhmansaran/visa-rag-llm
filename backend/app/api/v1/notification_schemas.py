from pydantic import BaseModel, field_serializer
from typing import Optional
from datetime import datetime

class NotificationResponse(BaseModel):
    """Notification response model."""
    id: int
    title: str
    message: str
    notification_type: str
    related_url: Optional[str] = None
    is_read: bool
    created_at: datetime

    @field_serializer('created_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None

    class Config:
        from_attributes = True
