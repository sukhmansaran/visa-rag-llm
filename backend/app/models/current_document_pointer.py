from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, ForeignKeyConstraint, func

if TYPE_CHECKING:
    from app.models.logical_document import LogicalDocument
    from app.models.document_version import DocumentVersion


class CurrentDocumentPointer(SQLModel, table=True):
    """
    Decoupled single authoritative pointer defining what version is currently active
    for a logical document. Guaranteed cross-document immune via composite FK.
    """
    __tablename__ = "current_document_pointers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["logical_document_id", "current_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_pointer_matching_doc_version",
            ondelete="RESTRICT",
        ),
    )

    logical_document_id: int = Field(
        primary_key=True,
        foreign_key="logical_documents.id",
    )
    current_version_id: int = Field(unique=True, nullable=False)
    promoted_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    promoted_by: str = Field(default="ingestion_pipeline", max_length=100)
    verified_chunk_count: int = Field(default=0)

    # Relationships
    logical_document: Optional["LogicalDocument"] = Relationship(back_populates="current_pointer")
    current_version: Optional["DocumentVersion"] = Relationship(
        sa_relationship_kwargs={"overlaps": "current_pointer,logical_document"}
    )
