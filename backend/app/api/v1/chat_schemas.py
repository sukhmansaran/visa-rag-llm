from typing import List, Dict, Any
from pydantic import BaseModel


class ChatMessage(BaseModel):
    """Chat message schema."""
    query: str
    country: str | None = None
    university: str | None = None
    sessionId: str | None = None
    chat_history: List[Dict[str, str]] | None = None


class SourceCitation(BaseModel):
    """Source citation schema."""
    url: str
    snippet: str
    scraped_at: str
    title: str | None = None


class ChatResponse(BaseModel):
    """Chat response schema with citations."""
    advice_text: str
    sources: List[SourceCitation]
    confidence: float  # 0.0 to 1.0
    escalate: bool  # True if human review recommended
    session_id: str | None = None  # Session ID for conversation continuity
    metadata: Dict[str, Any] = {}
