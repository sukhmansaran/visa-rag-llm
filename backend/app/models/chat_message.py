from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column


class ChatMessage(SQLModel, table=True):
    """Chat message history for conversations."""
    
    __tablename__ = "chat_messages"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    
    # Message content
    role: str = Field(max_length=20)  # user or assistant
    content: str = Field()
    
    # For assistant messages: store sources and message_metadata
    sources: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    confidence: Optional[float] = Field(default=None)
    message_metadata: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))  # Renamed from metadata
    
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Session grouping
    session_id: Optional[str] = Field(default=None, max_length=255, index=True)
