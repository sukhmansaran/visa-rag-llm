from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.models.source import Source
    from app.models.vector_chunk import VectorChunk


class Document(SQLModel, table=True):
    """Scraped documents with content snapshots."""
    
    __tablename__ = "documents"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    
    # Content hash for deduplication and change detection
    content_hash: str = Field(max_length=64, index=True)
    
    # Raw HTML/text
    raw_html: Optional[str] = Field(default=None)
    extracted_text: str = Field()
    
    # Storage URL for archival (S3/Firebase)
    storage_url: Optional[str] = Field(default=None, max_length=2048)
    
    scraped_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationships
    source: "Source" = Relationship(back_populates="documents")
    chunks: List["VectorChunk"] = Relationship(back_populates="document")
