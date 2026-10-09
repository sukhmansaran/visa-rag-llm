from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, Text, ForeignKeyConstraint, func

if TYPE_CHECKING:
    from app.models.logical_document import LogicalDocument
    from app.models.document_version import DocumentVersion


class VersionIndexingOperation(SQLModel, table=True):
    """
    Durable outbox record managing two-phase vector store write, verification,
    and asynchronous old-version vector tombstoning.
    """
    __tablename__ = "version_indexing_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["logical_document_id", "document_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_indexing_op_composite_doc_ver",
            ondelete="RESTRICT",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_version_id: int = Field(nullable=False, index=True)
    logical_document_id: int = Field(nullable=False, index=True)
    operation_type: str = Field(default="index_new_version", max_length=30)  # index_new_version, cleanup_superseded_version
    status: str = Field(default="pending", max_length=30, index=True)  # pending, in_progress, verified, failed, completed
    target_chunk_count: int = Field(default=0)
    verified_chunk_count: int = Field(default=0)
    vector_backend: str = Field(default="chroma", max_length=30)
    worker_lease_id: Optional[str] = Field(default=None, max_length=100)
    lease_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    retry_count: int = Field(default=0)
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Relationships
    document_version: Optional["DocumentVersion"] = Relationship()
