"""M4.4: on the verified path a sensitive answer holds only fully verified parts and always carries the disclaimer."""

import pytest

from app.core.visa_constitution import LEGAL_DISCLAIMER
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

REFUSED = "My study permit was refused for misrepresentation. Will I be banned from Canada?"
GUARANTEE = "If I show $40,000 in my bank account, will my study permit definitely be approved?"
PLAIN = "How many hours can I work off campus during my winter break?"
PAGE = {"text": "If you're found inadmissible for misrepresentation, you may be banned from coming to Canada for "
                "5 years. You can work unlimited hours off campus during scheduled breaks.",
        "score": 0.86, "authority_tier": 1, "freshness_weight": 1.0,
        "metadata": {"url": "https://www.canada.ca/misrepresentation.html", "title": "Misrepresentation"}}
GOOD = {"answer": "You may be banned from coming to Canada for 5 years.", "source_number": 1,
        "evidence_quote": "you may be banned from coming to Canada for 5 years"}


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return [PAGE]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.settings, "VERIFIED_MAX_ROUNDS", 1)
    intent_cache.clear()
    fake_llm.when(r"User Question:", "A free-written answer that nobody checked.")
    return fake_llm


async def run(question):
    intent_cache.clear()
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(question, db=object())
    return result, trace


@pytest.mark.asyncio
async def test_a_verified_sensitive_answer_carries_the_disclaimer(scripted):
    scripted.when(r"Question: My study permit was refused", GOOD)
    scripted.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    result, _ = await run(REFUSED)
    assert "banned from coming to Canada for 5 years" in result["answer"]
    assert "consult" in result["answer"].lower() and result["metrics"]["evidence"]["sensitive"] is True


@pytest.mark.asyncio
async def test_a_doubted_part_stays_labelled_in_a_sensitive_answer(scripted):
    """Owner decision 2026-10-26: code-verified is enough; dropping doubted parts removed a correct
    'approvals can never be guaranteed' answer (the model doubts 21-25% of correct claims)."""
    scripted.when(r"Question: My study permit was refused", GOOD)
    scripted.when(r"Claim:", {"supported": "partial", "reason": "not sure"})
    result, _ = await run(REFUSED)
    assert "5 years. [Source 1] (partially verified)" in result["answer"]
    assert "consult" in result["answer"].lower()


@pytest.mark.asyncio
async def test_a_part_failing_the_code_check_is_not_shown_in_a_sensitive_answer(scripted):
    scripted.when(r"Question: My study permit was refused", {**GOOD, "answer": "You will always be banned for 10 years."})
    result, _ = await run(REFUSED)
    assert "10 years" not in result["answer"] and "couldn't check an answer to this" in result["answer"]


@pytest.mark.asyncio
async def test_a_sensitive_answer_is_never_written_freely(scripted):
    scripted.when(r"Question: My study permit was refused", "not json")  # every evidence output unreadable
    result, trace = await run(REFUSED)
    assert "generation" not in [s["name"] for s in trace.steps]
    assert "free-written" not in result["answer"] and "couldn't check" in result["answer"]


@pytest.mark.asyncio
async def test_a_guarantee_question_always_gets_the_disclaimer(scripted, monkeypatch):
    from app.services.guardrails import legal_disclaimer as ld

    monkeypatch.setattr(ld.legal_disclaimer_engine, "detect_risk", lambda text: ([], []))  # detector silent
    scripted.when(r"Question: If I show \$40,000", {"not_covered": True})
    result, _ = await run(GUARANTEE)
    assert result["answer"].endswith(LEGAL_DISCLAIMER)


@pytest.mark.asyncio
async def test_a_plain_question_keeps_its_partially_verified_part(scripted):
    scripted.when(r"Question: How many hours", {
        "answer": "You can work unlimited hours off campus during scheduled breaks.", "source_number": 1,
        "evidence_quote": "You can work unlimited hours off campus during scheduled breaks."})
    scripted.when(r"Claim:", {"supported": "partial", "reason": "not sure"})
    result, _ = await run(PLAIN)
    assert "(partially verified)" in result["answer"] and "sensitive" not in result["metrics"]["evidence"]
