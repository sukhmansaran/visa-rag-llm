"""
Ingestion orchestration module for authoritative Canadian immigration data.
Includes both Milestone B2.2 IngestionOrchestrator and legacy IngestionService for backward compatibility.
"""

from app.services.scraper import scrape_with_retry
from app.services.chunker import chunk_document
from app.services.embeddings import embed_texts_batch
from app.services.vector_store import vector_store

from app.services.ingestion.orchestrator import (
    IngestionOrchestrator,
    IngestionOutcome,
    IngestionStepStatus,
    compute_canonical_url,
    compute_document_key,
)
from app.services.ingestion.legacy import (
    IngestionService,
    ingestion_service,
)

__all__ = [
    "IngestionOrchestrator",
    "IngestionOutcome",
    "IngestionStepStatus",
    "compute_canonical_url",
    "compute_document_key",
    "IngestionService",
    "ingestion_service",
    "scrape_with_retry",
    "chunk_document",
    "embed_texts_batch",
    "vector_store",
]

