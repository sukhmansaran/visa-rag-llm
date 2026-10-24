from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Chat message schema."""
    query: str = Field(..., min_length=1, max_length=2000)
    country: Optional[str] = Field(default=None, max_length=100)
    university: Optional[str] = Field(default=None, max_length=200)
    sessionId: Optional[str] = Field(default=None, max_length=64)
    # Chat history is never accepted from the client (R8); it is loaded from the DB by session.


class SourceCitation(BaseModel):
    """Source citation schema."""
    url: str
    snippet: str
    scraped_at: str
    title: str | None = None
    number: int | None = None  # the [Source N] that cites this page in the answer


class ChatResponse(BaseModel):
    """Chat response schema with citations."""
    advice_text: str
    sources: List[SourceCitation]
    confidence: float  # 0.0 to 1.0
    escalate: bool  # True if human review recommended
    session_id: str | None = None  # Session ID for conversation continuity
    metadata: Dict[str, Any] = {}
