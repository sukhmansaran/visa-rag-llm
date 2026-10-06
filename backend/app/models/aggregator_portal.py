from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, JSON

if TYPE_CHECKING:
    from app.models.seed_url import SeedURL
    from app.models.program_record import ProgramRecord


class AggregatorPortal(SQLModel, table=True):
    """Aggregator portal configuration for the crawler pipeline."""

    __tablename__ = "aggregator_portals"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, unique=True)
    tier: int = Field(ge=1, le=5, index=True)
    base_domains: list[str] = Field(default=[], sa_column=Column(JSON))
    category: str = Field(max_length=50)
    throttle_rps: float = Field(default=0.5)
    requires_js: bool = Field(default=False)
    extraction_config: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    seed_urls: List["SeedURL"] = Relationship(back_populates="portal")
    program_records: List["ProgramRecord"] = Relationship(back_populates="portal")
