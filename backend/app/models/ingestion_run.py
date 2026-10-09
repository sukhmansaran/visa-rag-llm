from datetime import datetime
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import DateTime, JSON, Text, func

if TYPE_CHECKING:
    from app.models.source import Source
    from app.models.document_version import DocumentVersion


class IngestionRun(SQLModel, table=True):
    """
    Execution audit record for batch or targeted ingestion cycles,
    recording provenance, metrics, and outcomes.
    """
    __tablename__ = "ingestion_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(unique=True, index=True, max_length=64, nullable=False)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id", index=True)
    status: str = Field(default="started", max_length=30, index=True)  # started, completed, failed, partial
    trigger_type: str = Field(default="manual", max_length=30)  # manual, scheduled, webhook

    # Metrics
    documents_fetched: int = Field(default=0)
    documents_updated: int = Field(default=0)
    documents_unchanged: int = Field(default=0)
    documents_failed: int = Field(default=0)

    error_summary: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    run_metadata: Dict[str, Any] = Field(
        default={},
        sa_column=Column(JSON, nullable=False, server_default='{}'),
    )

    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now()),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Relationships
    source: Optional["Source"] = Relationship()
    versions: List["DocumentVersion"] = Relationship(back_populates="ingestion_run")
