from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import DateTime, Text, UniqueConstraint, func


class MigrationUnmappedRecord(SQLModel, table=True):
    """
    Audit record capturing unmapped legacy documents or orphan vector chunks during backfill.
    """
    __tablename__ = "migration_unmapped_records"
    __table_args__ = (
        UniqueConstraint("legacy_table", "legacy_record_id", "issue_category", name="uq_unmapped_record"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    legacy_table: str = Field(max_length=50, nullable=False)  # documents, vector_chunks
    legacy_record_id: int = Field(nullable=False)
    issue_category: str = Field(max_length=50, nullable=False)  # missing_source, empty_content, orphaned_chunk
    raw_payload_snippet: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    detected_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    resolved: bool = Field(default=False)
