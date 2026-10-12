"""
Integration tests for Chroma persistence (R1) and similarity ranking (R2).
Verifies that data survives across fresh client instances and that cosine similarity
is computed correctly (identical vector yields similarity ~1.0 and ranks first).
"""

import tempfile
import pytest
from app.services.vector_store import ChromaVectorStore


@pytest.mark.asyncio
async def test_chroma_persists_across_fresh_instances():
    """Verify that data written by one ChromaVectorStore instance is read by a fresh instance."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        store1 = ChromaVectorStore(persist_directory=temp_dir)
        
        sample_chunk = {
            "text": "Study permit applicants must show adequate proof of funds.",
            "embedding": [0.1] * 768,
            "metadata": {"country": "Canada", "source_id": 101, "authority_tier": 1},
        }
        
        chunk_ids = await store1.upsert_chunks([sample_chunk])
        assert len(chunk_ids) == 1
        
        # Fresh store instance pointing to same directory
        store2 = ChromaVectorStore(persist_directory=temp_dir)
        results = await store2.search(query_embedding=[0.1] * 768, top_k=5)
        
        assert len(results) >= 1
        assert results[0]["id"] == chunk_ids[0]
        assert results[0]["text"] == sample_chunk["text"]


@pytest.mark.asyncio
async def test_chroma_cosine_similarity_ranking_and_exact_match():
    """Verify that an exact vector match produces similarity ~1.0 and ranks before distant vectors."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        store = ChromaVectorStore(persist_directory=temp_dir)
        
        # Dimension 4 for clean arithmetic
        # Vector A: exact target direction [1, 0, 0, 0]
        # Vector B: orthogonal direction [0, 1, 0, 0]
        chunk_a = {
            "text": "Exact match target document",
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "metadata": {"type": "target"},
        }
        chunk_b = {
            "text": "Orthogonal document",
            "embedding": [0.0, 1.0, 0.0, 0.0],
            "metadata": {"type": "orthogonal"},
        }
        
        await store.upsert_chunks([chunk_a, chunk_b])
        
        results = await store.search(query_embedding=[1.0, 0.0, 0.0, 0.0], top_k=2)
        
        assert len(results) == 2
        # Target must rank first
        assert results[0]["text"] == "Exact match target document"
        # Exact match should have similarity score ~ 1.0 (distance ~ 0.0)
        assert results[0]["score"] >= 0.99
        # Orthogonal document should have significantly lower score
        assert results[1]["score"] < 0.20
        assert results[0]["score"] > results[1]["score"]


@pytest.mark.asyncio
async def test_ingestion_invalidates_answer_cache_and_changes_content_version():
    """B16: new chunks clear cached answers in-process and change the cache-key version for all processes."""
    from app.services.cache_service import intent_cache

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        store = ChromaVectorStore(persist_directory=temp_dir)
        version_before = await store.content_version()

        intent_cache.set("Canada", "Student", "financial", "stale answer", version="v", query="funds?")
        assert intent_cache.get("Canada", "Student", "financial", version="v", query="funds?") == "stale answer"

        await store.upsert_chunks([{
            "text": "Updated proof of funds figure.",
            "embedding": [0.2] * 768,
            "metadata": {"country": "Canada", "source_id": 7},
        }])

        assert intent_cache.get("Canada", "Student", "financial", version="v", query="funds?") is None
        assert await store.content_version() != version_before
