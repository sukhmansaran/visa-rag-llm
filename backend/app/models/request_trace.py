from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, ForeignKey, Integer, Text
from sqlmodel import JSON, Field, SQLModel


class RequestTrace(SQLModel, table=True):
    """
    One record per chat request (M0.5): which steps ran, how long each took, every model call's
    accounting, and the versions that shaped the answer (principle 11). Question and answer are stored
    PII-redacted; rows older than TRACE_RETENTION_DAYS are deleted (D7) and go with the user's account.
    """

    __tablename__ = "request_traces"

    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: str = Field(max_length=36, unique=True, index=True)
    request_id: Optional[str] = Field(default=None, max_length=64)
    user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True),
    )
    session_id: Optional[str] = Field(default=None, max_length=64, index=True)
    endpoint: str = Field(max_length=40)                 # chat.answer | chat.stream
    status: str = Field(max_length=20, index=True)       # answered | refused | blocked | error
    source: Optional[str] = Field(default=None, max_length=40)  # pipeline metrics["source"]
    latency_ms: int = Field(default=0)

    model: Optional[str] = Field(default=None, max_length=100)
    model_digest: Optional[str] = Field(default=None, max_length=80)
    prompt_version: Optional[str] = Field(default=None, max_length=32)
    rules_version: Optional[str] = Field(default=None, max_length=32)
    kb_version: Optional[str] = Field(default=None, max_length=64)
    failed_over: bool = Field(default=False)

    steps: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    llm_calls: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    query_redacted: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    answer_redacted: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    error: Optional[str] = Field(default=None, max_length=500)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
