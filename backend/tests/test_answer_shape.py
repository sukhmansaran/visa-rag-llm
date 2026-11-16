"""A fast-path answer is never just a citation or a copied source header (app/services/answer_shape.py)."""

import pytest

from app.core.config import settings
from app.services import answer_shape
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.step_labels import describe
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as


def test_a_bare_citation_is_hollow():
    assert answer_shape.is_hollow("[Source 1]")
    assert answer_shape.is_hollow("No. [Source 1]")
    assert answer_shape.is_hollow("")
    assert not answer_shape.is_hollow("IELTS General Training is accepted. [Source 1]")
    assert not answer_shape.is_hollow("आपको भाषा परीक्षा देनी होगी")  # letters of any script count


def test_copied_headers_go_and_the_answer_stays():
    answer = ("[Source 1] (Tier 1 - Work off campus as an international student - Canada.ca)\n\n"
              "You cannot start working off campus before your studies begin. [Source 1]\n"
              "URL: https://www.canada.ca/en/work.html (Retrieved: 2026-10-19T09:51:45)")
    assert answer_shape.strip_echoed_framing(answer) == \
        "You cannot start working off campus before your studies begin. [Source 1]"


def test_an_inline_citation_line_is_not_a_header():
    answer = "- You need a study permit. [Source 2]"
    assert answer_shape.strip_echoed_framing(answer) == answer


def test_labels():
    assert describe({"name": "answer_shape", "hollow": False, "stripped": True}) is None
    assert describe({"name": "answer_shape", "hollow": True, "result": "retry"}).startswith("The first draft had no")
    assert describe({"name": "answer_shape", "hollow": True, "result": "fallback"}).startswith("Couldn't write")


# --- in the pipeline (fast path, both modes) ---

QUESTION = "Which IELTS test version is accepted for Express Entry?"
PAGE = "For Express Entry you must take IELTS General Training. IELTS Academic isn't accepted."


@pytest.fixture
def fast(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return [{"text": PAGE, "score": 0.85, "authority_tier": 1, "freshness_weight": 1.0,
                 "metadata": {"url": "https://www.canada.ca/en/language-test.html", "title": "Language tests"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.rule_engine, "try_rule_answer", lambda *a, **k: None)
    intent_cache.clear()
    yield fake_llm
    intent_cache.clear()


async def _ask(stream: bool):
    trace = TraceRecorder("test", query=QUESTION)
    with activate_trace(trace), routed_as("fast"):
        if not stream:
            return (await rp.rag_pipeline.process_query(QUESTION, db=object()))["answer"], trace
        done = {}
        async for event in rp.rag_pipeline.process_query_stream(QUESTION, db=object()):
            if event.get("type") == "done":
                done = event
        return done["full_response"], trace


def _step(trace):
    return next(s for s in trace.steps if s["name"] == "answer_shape")


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_a_hollow_answer_is_written_again(fast, stream):
    fast.when(r"no answer text", "For Express Entry you must take IELTS General Training. [Source 1]")
    fast.when(r"User Question:", "[Source 1]")
    answer, trace = await _ask(stream)
    assert "General Training" in answer
    assert _step(trace)["result"] == "retry"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_hollow_twice_says_so_and_is_not_cached(fast, stream):
    fast.when(r"User Question:", "[Source 1]")
    answer, trace = await _ask(stream)
    assert answer.startswith(answer_shape.HOLLOW_FALLBACK)
    assert _step(trace)["result"] == "fallback"
    calls = len(fast.calls)
    await _ask(stream)
    assert len(fast.calls) > calls  # asked the model again: the fallback wasn't served from the cache


@pytest.mark.asyncio
async def test_copied_header_is_removed_without_another_call(fast):
    fast.when(r"User Question:", "[Source 1] (Tier 1 - Language tests - Canada.ca)\n\nYou must take IELTS "
                                 "General Training. [Source 1]")
    answer, trace = await _ask(False)
    assert answer.startswith("You must take IELTS General Training.")
    assert _step(trace) == {**_step(trace), "stripped": True, "hollow": False}
    assert sum(c["kind"] == "chat" for c in fast.calls) == 1


@pytest.mark.asyncio
async def test_the_guard_can_be_switched_off(fast, monkeypatch):
    monkeypatch.setattr(settings, "ANSWER_SHAPE_GUARD", False)
    fast.when(r"User Question:", "[Source 1]")
    answer, trace = await _ask(False)
    assert answer.startswith("[Source 1]")
    assert not any(s["name"] == "answer_shape" for s in trace.steps)
