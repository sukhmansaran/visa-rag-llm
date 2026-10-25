"""M2.3: verified questions that ask several things get rules and sources per part and one answer."""

import pytest

from app.core.exceptions import AIServiceUnavailableError
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

FUNDS_AND_HOURS = ("As a single student, how much money do I need for living expenses, and how many hours can I "
                   "work off campus during classes?")
PARTS = ["As a single student, how much money do I need for living expenses?",
         "As a single student, how many hours can I work off campus during classes?"]
FUNDS_PAGE = "https://www.canada.ca/funds.html"
WORK_PAGE = "https://www.canada.ca/work.html"


def chunk(url, text, score=0.85):
    return {"text": text, "score": score, "authority_tier": 1, "freshness_weight": 1.0,
            "metadata": {"url": url, "title": url.rsplit("/", 1)[-1]}}


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    asked = []

    async def retrieve(query, **_):
        asked.append(query)
        if "money" in query and "hours" not in query:
            return [chunk(FUNDS_PAGE, "A single student needs proof of funds for living expenses.")]
        if "hours" in query and "money" not in query:
            return [chunk(WORK_PAGE, "Students may work up to 24 hours per week off campus during classes.")]
        return [chunk(WORK_PAGE, "Students may work up to 24 hours per week off campus during classes.")]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"Topics detected in it", {"sub_questions": PARTS})
    fake_llm.when(r"User Question:", "You need the funds [Source 1] and may work 24 hours a week [Source 2].")
    fake_llm.asked = asked
    return fake_llm


async def run(question, path):
    intent_cache.clear()
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace), routed_as(path):
        result = await rp.rag_pipeline.process_query(question, db=object())
    return result, trace


def answer_call(fake):
    return next(c for c in fake.calls if c["kind"] != "structured")


@pytest.mark.asyncio
async def test_the_fast_path_is_unchanged(scripted):
    result, trace = await run(FUNDS_AND_HOURS, "fast")
    assert "decomposition" not in [s["name"] for s in trace.steps]
    assert scripted.asked == [FUNDS_AND_HOURS]
    assert all(c["kind"] != "structured" for c in scripted.calls)


@pytest.mark.asyncio
async def test_one_question_on_the_verified_path_is_not_split(scripted):
    question = "How many hours can I work off campus during classes?"
    _, trace = await run(question, "verified")
    step = next(s for s in trace.steps if s["name"] == "decomposition")
    assert (step["method"], step["parts"]) == ("single", 1)
    assert scripted.asked == [question]


@pytest.mark.asyncio
async def test_a_question_with_two_parts_gets_rules_and_sources_for_each(scripted):
    result, trace = await run(FUNDS_AND_HOURS, "verified")
    step = next(s for s in trace.steps if s["name"] == "decomposition")
    assert (step["method"], step["parts"]) == ("model", 2)
    assert scripted.asked == PARTS  # one retrieval per part

    call = answer_call(scripted)
    # Rules for both parts: the rule engine used to stop at the first match (work hours) and drop the funds
    assert "23,448" in call["context"]  # the single-applicant amount from ircc_rules.yaml
    # both rule blocks, not just text that a retrieved page happens to share with one of them
    assert "STUDY PERMIT FINANCIAL REQUIREMENTS" in call["context"]
    assert "INTERNATIONAL STUDENT WORK REGULATIONS" in call["context"]
    assert FUNDS_PAGE in call["context"] and WORK_PAGE in call["context"]
    assert "This question has 2 parts" in call["user_prompt"] and PARTS[1] in call["user_prompt"]
    assert [s["url"] for s in result["sources"]] == [FUNDS_PAGE, WORK_PAGE]
    rules = next(s for s in trace.steps if s["name"] == "rules")
    retrieval = next(s for s in trace.steps if s["name"] == "retrieval")
    assert rules["parts"] == 2 and retrieval["parts"] == [1, 1]


@pytest.mark.asyncio
async def test_the_split_falls_back_when_the_model_is_down(scripted):
    scripted._rules.insert(0, {"regex": __import__("re").compile("Topics detected in it"),
                               "response": AIServiceUnavailableError(message="busy"), "queue": None})
    result, trace = await run(FUNDS_AND_HOURS, "verified")
    step = next(s for s in trace.steps if s["name"] == "decomposition")
    assert step["method"] == "fallback" and step["parts"] == 2
    assert len(scripted.asked) == 2 and result["metrics"]["llm_called"]


def test_each_part_gets_a_share_of_the_context():
    long_text = "x" * 1500
    part_chunks = [[chunk("https://a", long_text), chunk("https://a2", long_text), chunk("https://a3", long_text)],
                   [chunk("https://b", long_text), chunk("https://b2", long_text)]]
    merged = rp.RAGPipeline._merge_part_chunks(part_chunks, budget=4000)
    assert [c["metadata"]["url"] for c in merged] == ["https://a", "https://b"]  # the first part can't fill it


def test_a_part_always_gets_its_best_chunk_and_shared_chunks_appear_once():
    shared = chunk("https://shared", "same text")
    merged = rp.RAGPipeline._merge_part_chunks([[shared, chunk("https://a", "y" * 9000)],
                                                [shared, chunk("https://b", "z" * 9000)]], budget=1000)
    assert [c["metadata"]["url"] for c in merged] == ["https://shared", "https://b"]


@pytest.mark.asyncio
async def test_a_cached_fast_answer_does_not_stand_in_for_a_verified_one(scripted, monkeypatch):
    stored = {}

    def get_entry(*args, version, query):
        return stored.get((version, query))

    def set_entry(country, visa_type, intent, response, version, query, sources=None):
        stored[(version, query)] = {"response": response, "sources": sources or []}

    monkeypatch.setattr(rp.intent_cache, "get_entry", get_entry)
    monkeypatch.setattr(rp.intent_cache, "set", set_entry)
    trace = TraceRecorder("test", query=FUNDS_AND_HOURS)
    with activate_trace(trace), routed_as("fast"):
        await rp.rag_pipeline.process_query(FUNDS_AND_HOURS, db=object())
    assert stored and all(version.endswith(":fast") for version, _ in stored)
    trace = TraceRecorder("test", query=FUNDS_AND_HOURS)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(FUNDS_AND_HOURS, db=object())
    assert result["metrics"]["source"] != "cache"
    assert next(s for s in trace.steps if s["name"] == "cache")["hit"] is False
