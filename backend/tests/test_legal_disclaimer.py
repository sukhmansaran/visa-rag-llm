"""
Unit & Integration Tests for Legal & High-Risk Disclaimer Engine (Milestone 3 - Task 3.3).
Verifies:
1. High-risk topic detection across all 5 legal categories:
   - REFUSAL (refusals, section 216, GCMS notes, rejection letters)
   - MISREPRESENTATION (Section 40, false documents, 5-year ban)
   - INADMISSIBILITY (criminal, medical inadmissibility, TRP)
   - ENFORCEMENT (deportation, removal/exclusion orders, CBSA)
   - LITIGATION_APPEAL (judicial review, Federal Court, PFL, IAD)
2. Contextual disclaimer tailoring based on highest severity category.
3. Idempotent injection (no duplicate disclaimers).
4. Pipeline synchronous integration (process_query).
5. Pipeline streaming integration (process_query_stream).
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.services.guardrails.legal_disclaimer import (
    LegalDisclaimerEngine,
    RiskCategory,
    DISCLAIMER_REFUSAL,
    DISCLAIMER_MISREPRESENTATION,
    DISCLAIMER_INADMISSIBILITY_ENFORCEMENT,
    DISCLAIMER_GENERAL,
    legal_disclaimer_engine,
)
from app.services.rag_pipeline import RAGPipeline


@pytest.fixture
def engine():
    return LegalDisclaimerEngine()


# ==============================================================================
# 1. TOPIC DETECTION TESTS
# ==============================================================================

def test_detects_refusal_terms(engine):
    query = "My Canadian student visa got refused under section 216(1). How do I get GCMS notes?"
    categories, terms = engine.detect_risk(query)
    assert RiskCategory.REFUSAL in categories
    assert any("refused" in t.lower() or "section 216" in t.lower() or "gcms notes" in t.lower() for t in terms)


def test_detects_misrepresentation_terms(engine):
    query = "I was accused of misrepresentation under section 40 because of a fake job offer. Is there a 5-year ban?"
    categories, terms = engine.detect_risk(query)
    assert RiskCategory.MISREPRESENTATION in categories
    assert any("misrepresentation" in t.lower() or "section 40" in t.lower() for t in terms)


def test_detects_inadmissibility_terms(engine):
    query = "Will a prior DUI conviction result in criminal inadmissibility when entering Canada?"
    categories, terms = engine.detect_risk(query)
    assert RiskCategory.INADMISSIBILITY in categories


def test_detects_enforcement_and_deportation(engine):
    query = "The CBSA issued an exclusion order. Am I facing deportation from Canada?"
    categories, terms = engine.detect_risk(query)
    assert RiskCategory.ENFORCEMENT in categories


def test_detects_judicial_review_and_appeals(engine):
    query = "I received a procedural fairness letter (PFL) and want to file a judicial review in Federal Court."
    categories, terms = engine.detect_risk(query)
    assert RiskCategory.LITIGATION_APPEAL in categories


def test_benign_query_has_no_risk_categories(engine):
    query = "What is the tuition fee and proof of funds required for a university study permit?"
    categories, terms = engine.detect_risk(query)
    assert len(categories) == 0
    assert len(terms) == 0


# ==============================================================================
# 2. CONTEXTUAL DISCLAIMER SELECTION & EVALUATION
# ==============================================================================

def test_selects_misrepresentation_disclaimer(engine):
    disclaimer = engine.get_contextual_disclaimer([RiskCategory.MISREPRESENTATION, RiskCategory.REFUSAL])
    assert disclaimer == DISCLAIMER_MISREPRESENTATION
    assert "Section 40 IRPA" in disclaimer


def test_selects_enforcement_litigation_disclaimer(engine):
    disclaimer = engine.get_contextual_disclaimer([RiskCategory.ENFORCEMENT])
    assert disclaimer == DISCLAIMER_INADMISSIBILITY_ENFORCEMENT
    assert "Removal orders" in disclaimer


def test_selects_refusal_disclaimer(engine):
    disclaimer = engine.get_contextual_disclaimer([RiskCategory.REFUSAL])
    assert disclaimer == DISCLAIMER_REFUSAL
    assert "Visa refusal matters involve strict regulatory procedures" in disclaimer


def test_evaluates_and_appends_disclaimer(engine):
    query = "Why did IRCC refuse my visitor visa application?"
    response = "IRCC typically refuses visitor visas if ties to the home country are weak."

    eval_res = engine.evaluate(query, response)
    assert eval_res.is_high_risk is True
    assert "REFUSAL" in eval_res.risk_categories
    assert DISCLAIMER_REFUSAL in eval_res.annotated_text
    assert eval_res.annotated_text.startswith(response)


def test_prevents_duplicate_disclaimer_injection(engine):
    query = "Why was my visa refused?"
    response_with_disclaimer = (
        "Your visa was refused.\n\n"
        "> ⚠️ **Important Legal Advisory:** For refused applications, consult a Regulated Canadian Immigration Consultant (RCIC)."
    )

    eval_res = engine.evaluate(query, response_with_disclaimer)
    assert eval_res.is_high_risk is True
    # Length should not change because disclaimer is already present
    assert eval_res.annotated_text == response_with_disclaimer


# ==============================================================================
# 3. RAG PIPELINE INTEGRATION TESTS (SYNC & STREAM)
# ==============================================================================

@pytest.mark.asyncio
async def test_pipeline_sync_injects_disclaimer_on_refusal_query():
    """Verify synchronous process_query appends refusal disclaimer and sets telemetry."""
    pipeline = RAGPipeline()
    query = "My study permit was refused under Section 216(1). What should I do?"

    verified_chunk = [
        {
            "text": "Applicants refused under section 216(1) did not satisfy the officer they would leave Canada. You can request GCMS notes.",
            "authority_tier": 1,
            "score": 0.88,
            "metadata": {
                "url": "https://www.canada.ca/refusal-guidelines",
                "title": "IRCC Refusal Policies",
                "scraped_at": "2026-03-01",
                "authority_tier": 1,
            },
        }
    ]

    with patch("app.services.retrieval.retrieval_service.retrieve", new_callable=AsyncMock) as mock_retrieve, \
         patch("app.services.llm.llm_service.generate_answer", new_callable=AsyncMock) as mock_llm:

        mock_retrieve.return_value = verified_chunk
        mock_llm.return_value = "Under Section 216(1), the officer noted insufficient ties to your country. Request GCMS notes."

        result = await pipeline.process_query(query)

        assert result["metrics"]["high_risk_topic_detected"] is True
        assert "REFUSAL" in result["metrics"]["risk_categories"]
        assert "Important Legal Advisory" in result["answer"]
        assert "Regulated Canadian Immigration Consultant (RCIC)" in result["answer"]


@pytest.mark.asyncio
async def test_pipeline_stream_yields_disclaimer_chunk_on_misrepresentation_query():
    """Verify streaming process_query_stream yields disclaimer chunk and attaches telemetry."""
    pipeline = RAGPipeline()
    query = "I received a letter alleging Section 40 misrepresentation for a document."

    verified_chunk = [
        {
            "text": "Section 40 of IRPA covers misrepresentation, which may lead to a 5-year admissibility ban.",
            "authority_tier": 1,
            "score": 0.90,
            "metadata": {
                "url": "https://www.canada.ca/section-40-policy",
                "title": "Section 40 Enforcement",
                "scraped_at": "2026-03-01",
                "authority_tier": 1,
            },
        }
    ]

    async def mock_token_stream(*args, **kwargs):
        yield "Section 40 is a serious finding under Canadian immigration law.\n\n"
        yield "You must address this within the deadline provided in the letter."

    with patch("app.services.retrieval.retrieval_service.retrieve", new_callable=AsyncMock) as mock_retrieve, \
         patch("app.services.llm.llm_service.generate_answer_stream", side_effect=mock_token_stream):

        mock_retrieve.return_value = verified_chunk

        events = []
        done_event = None

        async for event in pipeline.process_query_stream(query):
            events.append(event)
            if event.get("type") == "done":
                done_event = event

        # Check disclaimer chunk was emitted in the stream
        disclaimer_chunks = [
            e for e in events
            if e.get("type") == "chunk" and "Critical Legal Warning (Section 40 IRPA)" in e.get("content", "")
        ]
        assert len(disclaimer_chunks) >= 1

        # Check terminal done event metadata
        assert done_event is not None
        assert done_event["metrics"]["high_risk_topic_detected"] is True
        assert "MISREPRESENTATION" in done_event["metrics"]["risk_categories"]
        assert "Section 40 IRPA" in done_event["full_response"]
