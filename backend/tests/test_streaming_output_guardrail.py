"""
Unit & Integration Tests for Sentence-Buffered Streaming Output Validator (Milestone 3 - Task 3.2).
Verifies:
1. Clean multi-token generation streams without interruption or false positives.
2. Mid-stream code fence injection is halted immediately, emitting guardrail_blocked and safe fallback.
3. Mid-stream secret / API key leak is halted immediately.
4. Mid-stream absolute legal guarantee is halted and replaced with legal disclaimer.
5. Compliant negative disclaimers ("IRCC does not guarantee") stream through safely.
6. RAG Pipeline streaming integration (process_query_stream) handles streaming guardrail events and telemetry.
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.services.guardrails.output_guardrail import (
    StreamingOutputValidator,
    OutputViolationType,
    SAFE_OUTPUT_FALLBACK,
    LEGAL_GUARANTEE_FALLBACK,
    validate_stream,
)
from app.services.rag_pipeline import RAGPipeline


async def async_token_generator(tokens):
    """Helper async generator yielding token strings one by one."""
    for token in tokens:
        yield token


@pytest.mark.asyncio
async def test_clean_stream_yields_all_clauses():
    """Legitimate immigration advice streams across clauses without blockage."""
    tokens = [
        "International students with a valid study permit ",
        "can work off-campus up to 20 hours per week.\n\n",
        "During scheduled academic breaks, ",
        "they are permitted to work full-time.",
    ]

    events = []
    async for event in validate_stream(async_token_generator(tokens)):
        events.append(event)

    # Verify no guardrail blockage
    blocked_events = [e for e in events if e.get("type") == "guardrail_blocked"]
    assert len(blocked_events) == 0

    # Verify chunks received
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert len(chunk_events) > 0
    full_output = "".join(c["content"] for c in chunk_events)
    assert "20 hours per week" in full_output
    assert "full-time" in full_output


@pytest.mark.asyncio
async def test_streaming_intercepts_mid_stream_code_block():
    """Stream aborts as soon as markdown code block fence begins appearing."""
    tokens = [
        "To apply for a study permit, follow these instructions:\n\n",
        "```python\n",
        "import ircc_api\n",
        "ircc_api.download_form('IMM1294')\n",
        "```",
    ]

    events = []
    async for event in validate_stream(async_token_generator(tokens)):
        events.append(event)

    # Verify guardrail blocked event fired
    blocked_events = [e for e in events if e.get("type") == "guardrail_blocked"]
    assert len(blocked_events) == 1
    assert blocked_events[0]["violation"] == OutputViolationType.CODE_BLOCK.value

    # Verify remediation chunk was provided
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert len(chunk_events) >= 1
    last_chunk = chunk_events[-1]
    assert last_chunk.get("replaced") is True
    assert SAFE_OUTPUT_FALLBACK in last_chunk["content"]


@pytest.mark.asyncio
async def test_streaming_intercepts_mid_stream_secret_leak():
    """Stream aborts immediately if API key or secret assignment pattern appears."""
    tokens = [
        "Your account is connected.\n\n",
        "Internal Key: sk-abcdef1234567890abcdef1234567890",
        " for backend auth.",
    ]

    events = []
    async for event in validate_stream(async_token_generator(tokens)):
        events.append(event)

    blocked_events = [e for e in events if e.get("type") == "guardrail_blocked"]
    assert len(blocked_events) == 1
    assert blocked_events[0]["violation"] == OutputViolationType.SECRET_LEAK.value

    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert SAFE_OUTPUT_FALLBACK in chunk_events[-1]["content"]


@pytest.mark.asyncio
async def test_streaming_intercepts_mid_stream_legal_guarantee():
    """Stream aborts if absolute approval guarantee is made mid-sentence."""
    tokens = [
        "If you show sufficient funds, ",
        "your study permit is 100% guaranteed to be approved!",
        " You will definitely get it.",
    ]

    events = []
    async for event in validate_stream(async_token_generator(tokens)):
        events.append(event)

    blocked_events = [e for e in events if e.get("type") == "guardrail_blocked"]
    assert len(blocked_events) == 1
    assert blocked_events[0]["violation"] == OutputViolationType.LEGAL_GUARANTEE.value

    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert LEGAL_GUARANTEE_FALLBACK in chunk_events[-1]["content"]


@pytest.mark.asyncio
async def test_streaming_allows_compliant_negative_disclaimer():
    """Ensure phrases like 'does not guarantee visa approval' stream cleanly."""
    tokens = [
        "Providing complete financial proof strengthens your file, ",
        "but IRCC does not guarantee visa approval.\n\n",
        "Final discretion belongs to the reviewing immigration officer.",
    ]

    events = []
    async for event in validate_stream(async_token_generator(tokens)):
        events.append(event)

    blocked_events = [e for e in events if e.get("type") == "guardrail_blocked"]
    assert len(blocked_events) == 0

    chunk_events = [e for e in events if e.get("type") == "chunk"]
    full_output = "".join(c["content"] for c in chunk_events)
    assert "does not guarantee visa approval" in full_output


@pytest.mark.asyncio
async def test_rag_pipeline_stream_integration_with_code_leak():
    """Integration test: pipeline process_query_stream terminates and records telemetry on code leak."""
    pipeline = RAGPipeline()
    query = "What are the study permit requirements?"

    verified_chunks = [
        {
            "text": "Study permit criteria require a Letter of Acceptance and sufficient funds.",
            "authority_tier": 1,
            "score": 0.90,
            "metadata": {
                "url": "https://www.canada.ca/study",
                "title": "Study Requirements",
                "scraped_at": "2026-03-01",
                "authority_tier": 1,
            },
        }
    ]

    async def mock_leaky_stream(*args, **kwargs):
        yield "Here is the guidance:\n\n"
        yield "```python\n"
        yield "print('unauthorized code')\n"
        yield "```"

    with patch("app.services.retrieval.retrieval_service.retrieve", new_callable=AsyncMock) as mock_retrieve, \
         patch("app.services.llm.llm_service.generate_answer_stream", side_effect=mock_leaky_stream):

        mock_retrieve.return_value = verified_chunks

        stream_events = []
        done_event = None

        async for event in pipeline.process_query_stream(query):
            stream_events.append(event)
            if event.get("type") == "done":
                done_event = event

        # Check guardrail blocked was emitted
        blocked_event = next((e for e in stream_events if e.get("type") == "guardrail_blocked"), None)
        assert blocked_event is not None
        assert blocked_event["violation"] == OutputViolationType.CODE_BLOCK.value

        # Check terminal done event metadata
        assert done_event is not None
        assert done_event["metrics"]["output_guardrail_remediated"] is True
        assert "CODE_BLOCK" in done_event["metrics"]["output_violations"]
        assert SAFE_OUTPUT_FALLBACK in done_event["full_response"]
