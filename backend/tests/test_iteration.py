"""M4.3 iteration: a verified-path part that isn't verified gets one more round with a refined search."""

import pytest

from app.core.config import settings
from app.services import iteration as it
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.evidence import PartResult
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

QUESTION = "Can I get a 3-year PGWP if my master's program was only 1 year long?"
FIRST_PAGE = {"text": "The length of your PGWP depends on the length of your study program.", "score": 0.8,
              "authority_tier": 1, "freshness_weight": 1.0,
              "metadata": {"url": "https://www.canada.ca/pgwp-about.html", "title": "About the PGWP"}}
RETRY_PAGE = {"text": "Master's degree graduates can get a 3-year PGWP if the master's program was at least 8 months "
                      "long, even if it was shorter than 2 years.", "score": 0.78, "authority_tier": 1,
              "freshness_weight": 1.0, "metadata": {"url": "https://www.canada.ca/pgwp-length.html", "title": "Length"}}
GOOD = {"answer": "Yes, a master's program of at least 8 months can lead to a 3-year PGWP.", "source_number": 2,
        "evidence_quote": "Master's degree graduates can get a 3-year PGWP if the master's program was at least 8 months "
                          "long, even if it was shorter than 2 years."}


def test_refine_query_spells_out_acronyms_and_adds_topic_words():
    refined = it.refine_query("How long is a PGWP?")
    assert refined.startswith("How long is a PGWP?")
    assert "Post-graduation work permit" in refined and "eligibility length" in refined
    assert it.refine_query("Do I need biometrics?").count("biometrics") >= 2


def test_a_retry_is_kept_only_when_it_is_better():
    first = PartResult("q", "unverified")
    assert it.better(first, PartResult("q", "verified")).status == "verified"
    assert it.better(first, PartResult("q", "not_covered")) is first
    assert it.better(PartResult("q", "invalid"), PartResult("q", "not_covered")).status == "not_covered"


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    searches = []

    async def retrieve(query, top_k=4, **_):
        searches.append(query)
        return [FIRST_PAGE] if len(searches) == 1 else [FIRST_PAGE, RETRY_PAGE]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.rule_engine, "try_rule_answer", lambda *a, **k: None)
    intent_cache.clear()
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.when(r"User Question:", "unused")
    fake_llm.searches = searches
    return fake_llm


async def run():
    intent_cache.clear()
    trace = TraceRecorder("test", query=QUESTION)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(QUESTION, db=object())
    return result, trace


@pytest.mark.asyncio
async def test_a_failed_part_is_verified_on_the_retry_and_its_new_page_is_cited(scripted):
    # first round: the only page doesn't answer -> not covered; retry sees the new page -> verified
    scripted.when(r"Question: Can I get a 3-year PGWP", [{"not_covered": True}, GOOD])
    result, trace = await run()
    retry = next(s for s in trace.steps if s["name"] == "retry")
    assert (retry["first"], retry["new_chunks"], retry["retry"], retry["kept"]) == ("not_covered", 1, "verified", "retry")
    assert len(scripted.searches) == 2 and "Post-graduation work permit" in scripted.searches[1]
    assert "[Source 2]" in result["answer"] and "8 months" in result["answer"]
    assert [(s["url"], s["numbers"]) for s in result["sources"]] == [
        ("https://www.canada.ca/pgwp-about.html", [1]), ("https://www.canada.ca/pgwp-length.html", [2])]
    assert result["metrics"]["evidence"]["improved_by_retry"] == 1


@pytest.mark.asyncio
async def test_a_retry_that_finds_nothing_new_keeps_the_first_answer(scripted, monkeypatch):
    async def same(query, top_k=4, **_):
        scripted.searches.append(query)
        return [FIRST_PAGE]

    monkeypatch.setattr(rp.retrieval_service, "retrieve", same)
    scripted.when(r"Question: Can I get a 3-year PGWP", {"not_covered": True})
    result, trace = await run()
    retry = next(s for s in trace.steps if s["name"] == "retry")
    assert retry["new_chunks"] == 0 and "retry" not in retry
    assert result["answer"].startswith("The official sources I have don't cover this")


@pytest.mark.asyncio
async def test_no_retry_once_the_time_budget_is_used(scripted, monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_RETRY_BEFORE_SECONDS", -1)
    scripted.when(r"Question: Can I get a 3-year PGWP", [{"not_covered": True}, GOOD])
    result, trace = await run()
    assert next(s for s in trace.steps if s["name"] == "retry")["skipped"] == "time_budget"
    assert len(scripted.searches) == 1


@pytest.mark.asyncio
async def test_retries_can_be_switched_off(scripted, monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_MAX_ROUNDS", 1)
    scripted.when(r"Question: Can I get a 3-year PGWP", [{"not_covered": True}, GOOD])
    _, trace = await run()
    assert "retry" not in [s["name"] for s in trace.steps] and len(scripted.searches) == 1


@pytest.mark.asyncio
async def test_a_verified_part_is_not_retried(scripted, monkeypatch):
    async def both(query, top_k=4, **_):
        scripted.searches.append(query)
        return [FIRST_PAGE, RETRY_PAGE]

    monkeypatch.setattr(rp.retrieval_service, "retrieve", both)
    scripted.when(r"Question: Can I get a 3-year PGWP", GOOD)
    _, trace = await run()
    assert "retry" not in [s["name"] for s in trace.steps] and len(scripted.searches) == 1


@pytest.mark.asyncio
async def test_a_chunk_cut_to_fit_the_context_is_seen_whole_on_the_retry(scripted, monkeypatch):
    """The answer sits past the cut of the last chunk: the first round can't see it, so the retry must not skip
    that chunk as already shown."""
    long_page = {**RETRY_PAGE, "text": "Some graduates can combine programs. " * 8 + RETRY_PAGE["text"]}

    async def retrieve(query, top_k=4, **_):  # a fresh copy each search, as from the vector store
        scripted.searches.append(query)
        return [dict(FIRST_PAGE), dict(long_page)]

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(settings, "RAG_CONTEXT_CHARS", 700)  # the second chunk is cut before its last sentence
    scripted.when(r"Question: Can I get a 3-year PGWP", [{"not_covered": True}, GOOD])
    result, trace = await run()
    first_context = next(c for c in scripted.calls if "Question: Can I get" in c["user_prompt"])
    assert "even if it was shorter than 2 years" not in first_context["user_prompt"] + first_context["context"]
    retry = next(s for s in trace.steps if s["name"] == "retry")
    assert (retry["new_chunks"], retry["retry"], retry["kept"]) == (1, "verified", "retry")
    assert "8 months" in result["answer"]


@pytest.mark.asyncio
async def test_a_chunk_seen_whole_is_not_shown_again_on_the_retry(scripted, monkeypatch):
    async def retrieve(query, top_k=4, **_):
        scripted.searches.append(query)
        return [dict(FIRST_PAGE)]

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    scripted.when(r"Question: Can I get a 3-year PGWP", {"not_covered": True})
    _, trace = await run()
    assert next(s for s in trace.steps if s["name"] == "retry")["new_chunks"] == 0
