from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, JSON, Column
from sqlalchemy import ForeignKeyConstraint, CheckConstraint

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_version import DocumentVersion
    from app.models.logical_document import LogicalDocument


class VectorChunk(SQLModel, table=True):
    """Text chunks with embeddings stored in vector database."""
    
    __tablename__ = "vector_chunks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('staging', 'active', 'superseded', 'tombstoned')",
            name="chk_vector_chunk_status",
        ),
        CheckConstraint(
            "((document_version_id IS NULL AND logical_document_id IS NULL) OR (document_version_id IS NOT NULL AND logical_document_id IS NOT NULL))",
            name="chk_vector_chunks_paired_doc_ver",
        ),
        ForeignKeyConstraint(
            ["logical_document_id", "document_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_vector_chunks_composite_doc_ver",
            ondelete="RESTRICT",
        ),
    )
    
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="documents.id", index=True)
    
    # Versioning extensions
    document_version_id: Optional[int] = Field(default=None, index=True)
    logical_document_id: Optional[int] = Field(default=None, index=True)
    chunk_id: Optional[str] = Field(default=None, unique=True, max_length=255)
    status: str = Field(default="active", max_length=20, index=True)

    # Chunk index within the document
    chunk_index: int = Field()
    
    # Actual text content
    text: str = Field()
    
    # Vector database ID (Chroma/Pinecone)
    vector_id: str = Field(unique=True, index=True, max_length=255)
    
    # Authority Tier: 1 = IRCC/Gov, 2 = DLI Colleges, 3 = Recognized Orgs, 4 = Third-Party
    authority_tier: int = Field(default=1, index=True)

    # Date when the policy or regulation officially becomes effective
    effective_date: Optional[datetime] = Field(default=None)

    # Metadata stored in vector DB: {url, title, page_no, scraped_at, country, source_type}
    chunk_metadata: Dict[str, Any] = Field(sa_column=Column(JSON))
    
    # Relationships
    document: "Document" = Relationship(back_populates="chunks")
    document_version: Optional["DocumentVersion"] = Relationship(back_populates="chunks")
