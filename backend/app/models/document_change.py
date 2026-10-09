from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, Text, JSON, UniqueConstraint, ForeignKeyConstraint, func

if TYPE_CHECKING:
    from app.models.logical_document import LogicalDocument
    from app.models.document_version import DocumentVersion


class DocumentChange(SQLModel, table=True):
    """
    Deterministic structural diff and severity assessment between two document versions.
    """
    __tablename__ = "document_changes"
    __table_args__ = (
        UniqueConstraint("logical_document_id", "new_version_id", name="uq_doc_change_pair"),
        ForeignKeyConstraint(
            ["logical_document_id", "new_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_doc_change_new_composite_ver",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["logical_document_id", "old_version_id"],
            ["document_versions.logical_document_id", "document_versions.id"],
            name="fk_doc_change_old_composite_ver",
            ondelete="RESTRICT",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    logical_document_id: int = Field(nullable=False, index=True)
    old_version_id: Optional[int] = Field(default=None)  # Nullable for initial_version
    new_version_id: int = Field(nullable=False)
    change_type: str = Field(default="initial_version", max_length=50)
    severity: str = Field(default="medium", max_length=20, index=True)  # low, medium, high, critical
    review_status: str = Field(default="auto_approved", max_length=30)  # auto_approved, review_required, reviewed
    requires_notification: bool = Field(default=False)
    diff_patch: Dict[str, Any] = Field(default={}, sa_column=Column(JSON, nullable=False))
    summary: str = Field(sa_column=Column(Text, nullable=False))
    detected_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )

    # Relationships
    new_version: Optional["DocumentVersion"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DocumentChange.new_version_id]"}
    )
    old_version: Optional["DocumentVersion"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DocumentChange.old_version_id]"}
    )
