from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, func

if TYPE_CHECKING:
    from app.models.source import Source
    from app.models.document_version import DocumentVersion
    from app.models.current_document_pointer import CurrentDocumentPointer


class LogicalDocument(SQLModel, table=True):
    """
    Stable representation of an authoritative Canadian immigration document entity,
    independent of evolving version revisions.
    """
    __tablename__ = "logical_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True, nullable=False)
    document_key: str = Field(unique=True, index=True, max_length=64, nullable=False)
    primary_url: str = Field(max_length=2048, nullable=False)
    canonical_url: Optional[str] = Field(default=None, max_length=2048)
    title: str = Field(max_length=512, nullable=False)
    document_type: str = Field(default="policy_guide", max_length=50, index=True)
    status: str = Field(default="active", max_length=30, index=True)  # active, unavailable, archived
    
    # Audit timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    # Provenance tracking for upstream source availability
    last_verified_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_failure_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_failure_category: Optional[str] = Field(default=None, max_length=50)
    last_failure_http_status: Optional[int] = Field(default=None)

    # Relationships
    source: "Source" = Relationship()
    versions: List["DocumentVersion"] = Relationship(back_populates="logical_document")
    current_pointer: Optional["CurrentDocumentPointer"] = Relationship(back_populates="logical_document")
