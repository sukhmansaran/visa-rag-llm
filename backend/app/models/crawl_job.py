from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class CrawlJob(SQLModel, table=True):
    """Tracks the state and statistics of a crawl execution."""

    __tablename__ = "crawl_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(unique=True, index=True, max_length=64)  # UUID
    status: str = Field(default="pending", max_length=20)  # pending, running, paused, completed, failed, expired
    seed_urls: list[str] = Field(default=[], sa_column=Column(JSON))
    config: dict = Field(default={}, sa_column=Column(JSON))  # CrawlJobConfig serialized

    # Statistics
    pages_crawled: int = Field(default=0)
    pages_relevant: int = Field(default=0)
    pages_stored: int = Field(default=0)
    pages_failed: int = Field(default=0)
    pages_duplicate: int = Field(default=0)
    pages_robots_blocked: int = Field(default=0)

    # Timestamps
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    paused_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
