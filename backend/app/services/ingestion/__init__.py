"""
Ingestion: scrape an official page, chunk its verbatim text, embed, store; one retrievable version per page.

M0.14: this is the only ingestion pipeline. The unused B2.2 IngestionOrchestrator (never wired in; it indexed
zero-vector placeholder embeddings and its supersession never reached the vector store) was removed with its
fetcher and normalizer; they remain in git history.
"""

from app.services.scraper import scrape_with_retry
from app.services.chunker import chunk_document
from app.services.embeddings import embed_texts_batch
from app.services.vector_store import vector_store

from app.services.ingestion.legacy import (
    IngestionService,
    ingestion_service,
)

__all__ = [
    "IngestionService",
    "ingestion_service",
    "scrape_with_retry",
    "chunk_document",
    "embed_texts_batch",
    "vector_store",
]
