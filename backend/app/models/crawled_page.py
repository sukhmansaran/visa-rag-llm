from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class CrawledPage(SQLModel, table=True):
    """Metadata for each crawled page within a crawl job."""

    __tablename__ = "crawled_pages"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, max_length=64)
    url: str = Field(max_length=2048, index=True)
    parent_url: Optional[str] = Field(default=None, max_length=2048)
    depth: int = Field(default=0)

    http_status: Optional[int] = Field(default=None)
    fetch_duration_ms: Optional[int] = Field(default=None)
    content_hash: Optional[str] = Field(default=None, max_length=64, index=True)

    classification: str = Field(default="pending", max_length=20)  # relevant, irrelevant, pending, skipped
    matched_keywords: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))

    status: str = Field(default="pending", max_length=20)  # pending, fetched, processed, failed, robots_blocked, duplicate
    error_message: Optional[str] = Field(default=None)
    worker_id: Optional[str] = Field(default=None, max_length=100)

    document_id: Optional[int] = Field(default=None, foreign_key="documents.id")
    fetched_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
