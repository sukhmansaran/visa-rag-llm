from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, ForeignKeyConstraint, func

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.logical_document import LogicalDocument
    from app.models.document_version import DocumentVersion


class LegacyDocumentVersionMapping(SQLModel, table=True):
    """
    Persistent mapping from every legacy documents.id to its target version.
    Preserves 100% legacy provenance, including deduplicated snapshots.
    """
    __tablename__ = "legacy_document_version_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["logical_document_id", "document_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_legacy_map_composite_doc_ver",
            ondelete="RESTRICT",
        ),
    )

    legacy_document_id: int = Field(
        primary_key=True,
        foreign_key="documents.id",
    )
    logical_document_id: int = Field(nullable=False, index=True)
    document_version_id: int = Field(nullable=False, index=True)
    is_deduplicated: bool = Field(default=False)
    mapped_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    # Relationships
    legacy_document: Optional["Document"] = Relationship()
    document_version: Optional["DocumentVersion"] = Relationship()
