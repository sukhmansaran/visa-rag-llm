"""
Unit and integration tests for Task 2.2: Source Authority Tiering (Tiers 1 to 4) & Algorithmic Confidence Scoring.
Verifies:
1. Schema extensions for Source and VectorChunk models.
2. Authority tier inference from URLs, source types, and metadata.
3. Reranking prioritization of Tier 1 official sources over Tier 4 blogs.
4. Conflict resolution filter: Exclusion of Tier 4 blogs when strong Tier 1 official sources exist.
5. Mathematical algorithmic confidence scoring: similarity * 0.4 + authority * 0.4 + freshness * 0.2.
6. Refusal when confidence is INSUFFICIENT (< 0.35).
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.models.source import Source
from app.models.vector_chunk import VectorChunk
from app.services.retrieval import retrieval_service
from app.services.rag_pipeline import rag_pipeline, UNVERIFIED_EVIDENCE_REFUSAL


# ==========================================
# 1. SCHEMA EXTENSION TESTS (Sub-task 2.2.1)
# ==========================================
def test_source_model_authority_tier_fields():
    """Verify Source model has authority_tier and effective_date."""
    now = datetime.utcnow()
    source = Source(
        name="IRCC Official",
        url="https://www.canada.ca/en/immigration-refugees-citizenship.html",
        source_type="official",
        authority_tier=1,
        effective_date=now,
    )
    assert source.authority_tier == 1
    assert source.effective_date == now

    # Default fallback
    source_default = Source(name="Test", url="https://example.com", source_type="blog")
    assert source_default.authority_tier == 1


def test_vector_chunk_model_authority_tier_fields():
    """Verify VectorChunk model has authority_tier and effective_date."""
    now = datetime.utcnow()
    chunk = VectorChunk(
        document_id=1,
        chunk_index=0,
        text="Sample immigration regulation text",
        vector_id="vec_001",
        chunk_metadata={"country": "Canada"},
        authority_tier=2,
        effective_date=now,
    )
    assert chunk.authority_tier == 2
    assert chunk.effective_date == now


# ==========================================
# 2. TIER INFERENCE & RERANKING TESTS (Sub-task 2.2.2)
# ==========================================
def test_infer_authority_tier_from_url_and_type():
    """Verify authority tier inference rules."""
    # Tier 1
    assert retrieval_service.infer_authority_tier({"metadata": {"url": "https://www.canada.ca/study"}}) == 1
    assert retrieval_service.infer_authority_tier({"metadata": {"source_type": "embassy"}}) == 1

    # Tier 2
    assert retrieval_service.infer_authority_tier({"metadata": {"url": "https://www.utoronto.ca/international"}}) == 2
    assert retrieval_service.infer_authority_tier({"metadata": {"source_type": "university"}}) == 2

    # Tier 3
    assert retrieval_service.infer_authority_tier({"metadata": {"url": "https://ontario.ca/pnp"}}) == 3
    assert retrieval_service.infer_authority_tier({"metadata": {"source_type": "organization"}}) == 3

    # Tier 4
    assert retrieval_service.infer_authority_tier({"metadata": {"url": "https://myvisablog.com/forum"}}) == 4
    assert retrieval_service.infer_authority_tier({"metadata": {"source_type": "blog"}}) == 4


def test_tier_weighted_reranking_prioritizes_tier1():
    """Verify Tier 1 official sources outrank Tier 4 blogs despite similar base vector scores."""
    tier1_chunk = {
        "text": "Official IRCC study permit requirements state proof of funds is CAD $20,635.",
        "score": 0.82,
        "metadata": {
            "url": "https://www.canada.ca/study-permits",
            "source_type": "official",
            "authority_tier": 1,
            "scraped_at": datetime.utcnow().isoformat(),
        }
    }
    tier4_chunk = {
        "text": "According to blog discussions, you only need 10,000 CAD.",
        "score": 0.84,  # slightly higher raw similarity score
        "metadata": {
            "url": "https://random-forum.com/canada-visa",
            "source_type": "blog",
            "authority_tier": 4,
            "scraped_at": datetime.utcnow().isoformat(),
        }
    }

    results = [tier4_chunk, tier1_chunk]
    reranked = retrieval_service._rerank(results, query="How much proof of funds for study permit?")

    # Conflict filter should drop the Tier 4 blog because a strong Tier 1 source exists
    assert len(reranked) == 1
    assert reranked[0]["authority_tier"] == 1
    assert "Official IRCC" in reranked[0]["text"]


def test_conflict_filter_drops_tier4_when_strong_tier1_present():
    """Verify conflict resolution automatically eliminates Tier 4 third-party blogs when strong Tier 1 exists."""
    results = [
        {
            "text": "Official Gazette: PGWP rules updated for 2026.",
            "score": 0.78,
            "metadata": {"url": "https://www.canada.ca/ircc", "authority_tier": 1}
        },
        {
            "text": "Old blog rumors about PGWP.",
            "score": 0.65,
            "metadata": {"url": "https://visa-rumors.blog", "authority_tier": 4}
        },
        {
            "text": "University of Waterloo international student advisory.",
            "score": 0.70,
            "metadata": {"url": "https://uwaterloo.ca", "authority_tier": 2}
        }
    ]

    reranked = retrieval_service._rerank(results, query="PGWP 2026 rules")

    tiers_present = [r["authority_tier"] for r in reranked]
    assert 1 in tiers_present
    assert 2 in tiers_present
    assert 4 not in tiers_present  # Dropped by conflict filter


# ==========================================
# 3. ALGORITHMIC CONFIDENCE TESTS (Sub-task 2.2.3)
# ==========================================
def test_algorithmic_confidence_calculation_high():
    """Verify high confidence calculation (similarity 0.85, Tier 1, fresh)."""
    chunks = [{
        "score": 0.85,
        "authority_weight": 1.0,  # Tier 1
        "freshness_weight": 1.0,  # < 90 days
    }]
    # 0.85 * 0.4 + 1.0 * 0.4 + 1.0 * 0.2 = 0.34 + 0.40 + 0.20 = 0.94
    eval_result = rag_pipeline.calculate_algorithmic_confidence(chunks)
    assert eval_result["score"] == 0.94
    assert eval_result["level"] == "HIGH"


def test_algorithmic_confidence_calculation_insufficient():
    """Verify low similarity and low authority triggers INSUFFICIENT classification."""
    chunks = [{
        "score": 0.30,
        "authority_weight": 0.3,  # Tier 4
        "freshness_weight": 0.5,  # stale
    }]
    # 0.30 * 0.4 + 0.30 * 0.4 + 0.50 * 0.2 = 0.12 + 0.12 + 0.10 = 0.34 (< 0.35)
    eval_result = rag_pipeline.calculate_algorithmic_confidence(chunks)
    assert eval_result["score"] == 0.34
    assert eval_result["level"] == "INSUFFICIENT"


@pytest.mark.asyncio
async def test_insufficient_confidence_triggers_grounded_refusal():
    """Verify queries with insufficient confidence refuse to hallucinate."""
    query = "What is the secret trick for PR?"
    low_confidence_chunk = {
        "text": "A vague sentence about general immigration.",
        "score": 0.25,
        "authority_weight": 0.3,
        "freshness_weight": 0.5,
        "authority_tier": 4,
    }

    with patch("app.services.retrieval.retrieval_service.retrieve", new_callable=AsyncMock) as mock_retrieve, \
         patch("app.services.cache_service.intent_cache.get", return_value=None), \
         patch("app.services.rule_engine.rule_engine.try_rule_answer", return_value=None), \
         patch("app.services.llm.llm_service.generate_answer", new_callable=AsyncMock) as mock_llm:
        mock_retrieve.return_value = [low_confidence_chunk]

        result = await rag_pipeline.process_query(query)

        assert result["answer"] == UNVERIFIED_EVIDENCE_REFUSAL
        assert result["metrics"]["confidence_level"] == "INSUFFICIENT"
        assert result["metrics"]["source"] == "insufficient_confidence_refusal"
        assert result["metrics"]["llm_called"] is False
        mock_llm.assert_not_called()
