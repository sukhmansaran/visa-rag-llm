from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON

if TYPE_CHECKING:
    from app.models.aggregator_portal import AggregatorPortal


class SeedURL(SQLModel, table=True):
    """Seed URLs for crawl jobs with per-seed configuration."""

    __tablename__ = "seed_urls"

    id: Optional[int] = Field(default=None, primary_key=True)
    portal_id: int = Field(foreign_key="aggregator_portals.id", index=True)
    url: str = Field(max_length=2048, unique=True)
    max_depth: int = Field(default=3)
    allowed_domains: list[str] = Field(default=[], sa_column=Column(JSON))
    crawl_schedule: str = Field(default="weekly")  # daily, weekly, monthly
    is_active: bool = Field(default=True)
    last_crawled_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    portal: "AggregatorPortal" = Relationship(back_populates="seed_urls")
