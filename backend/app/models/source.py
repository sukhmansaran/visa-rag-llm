from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.change import Change


class Source(SQLModel, table=True):
    """Authoritative sources to scrape (embassy sites, university portals, etc.)."""
    
    __tablename__ = "sources"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True, index=True, max_length=2048)
    name: str = Field(max_length=255)
    country: Optional[str] = Field(default=None, max_length=100, index=True)
    
    # Source type: embassy, university, news, official
    source_type: str = Field(max_length=50, index=True)
    
    # Priority: 1 (highest) to 5 (lowest)
    priority: int = Field(default=3)
    
    # Scrape frequency in hours (24 = daily, 168 = weekly)
    scrape_frequency: int = Field(default=168)
    
    last_scraped_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True)
    portal_id: Optional[int] = Field(default=None, foreign_key="aggregator_portals.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    documents: List["Document"] = Relationship(back_populates="source")
    changes: List["Change"] = Relationship(back_populates="source")
