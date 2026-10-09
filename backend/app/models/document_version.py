from datetime import datetime
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, Text, JSON, UniqueConstraint, func

if TYPE_CHECKING:
    from app.models.logical_document import LogicalDocument
    from app.models.vector_chunk import VectorChunk
    from app.models.ingestion_run import IngestionRun


class DocumentVersion(SQLModel, table=True):
    """
    Immutable, content-addressed version snapshot of a logical document.
    """
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("logical_document_id", "version_number", name="uq_doc_ver_sequence"),
        # Composite unique constraint enabling universal composite foreign keys from child tables:
        UniqueConstraint("logical_document_id", "id", name="uq_doc_ver_composite_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    logical_document_id: int = Field(foreign_key="logical_documents.id", index=True, nullable=False)
    ingestion_run_id: Optional[int] = Field(default=None, foreign_key="ingestion_runs.id", index=True)
    version_number: int = Field(nullable=False)
    lifecycle_state: str = Field(default="fetched", max_length=30, index=True)
    
    requested_url: str = Field(max_length=2048, nullable=False)
    final_url: str = Field(max_length=2048, nullable=False)
    
    # Hashing
    raw_content_hash: Optional[str] = Field(default=None, max_length=64)
    normalized_content_hash: Optional[str] = Field(default=None, max_length=64, index=True)
    legacy_scraper_hash: Optional[str] = Field(default=None, max_length=64)
    
    # HTTP Validators
    etag: Optional[str] = Field(default=None, max_length=255)
    last_modified: Optional[str] = Field(default=None, max_length=255)
    content_type: str = Field(default="text/html", max_length=100)
    
    # Measurements
    raw_byte_count: int = Field(default=0)
    normalized_char_count: int = Field(default=0)
    language: Optional[str] = Field(default="en", max_length=20)
    
    # Statutory / Policy Dates
    published_date: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    effective_date: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    retrieved_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    
    # Content
    extracted_text: str = Field(sa_column=Column(Text, nullable=False))
    raw_html: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    version_metadata: Dict[str, Any] = Field(
        default={},
        sa_column=Column("metadata", JSON, nullable=False, server_default='{}'),
    )
    
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    # Relationships
    logical_document: "LogicalDocument" = Relationship(back_populates="versions")
    ingestion_run: Optional["IngestionRun"] = Relationship(back_populates="versions")
    chunks: List["VectorChunk"] = Relationship(back_populates="document_version")
