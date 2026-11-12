"""M6.3 time budget: once the budget is used, a verified answer starts no new part; the parts checked so far are
returned and the rest are labelled, instead of the job being stopped with nothing to show."""

import pytest

from app.core.config import settings
from app.services import evidence as ev
from app.services import rag_pipeline as rp
from app.services import verified_cache
from app.services.cache_service import intent_cache
from app.services.step_labels import describe
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

QUESTION = ("As a single student, how much money do I need for living expenses, and how many hours can I "
            "work off campus during classes?")
PARTS = ["As a single student, how much money do I need for living expenses?",
         "As a single student, how many hours can I work off campus during classes?"]
WORK = "Students may work up to 24 hours per week off campus during classes."
FUNDS = "A single student needs CAD $23,448 as proof of funds for living expenses."
FUNDS_ANSWER = {"answer": "You need CAD $23,448.", "source_number": 1, "evidence_quote": FUNDS}


def chunk(url, text):
    return {"text": text, "score": 0.85, "authority_tier": 1, "freshness_weight": 1.0,
            "metadata": {"url": url, "title": url.rsplit("/", 1)[-1]}}


@pytest.fixture
def scripted(fake_llm, monkeypatch):
    async def retrieve(query, **_):
        return [chunk("https://www.canada.ca/funds.html", FUNDS)] if "money" in query else [
            chunk("https://www.canada.ca/work.html", WORK)]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(rp.rule_engine, "try_rule_answer", lambda *a, **k: None)
    intent_cache.clear()
    fake_llm.when(r"Topics detected in it", {"sub_questions": PARTS})
    fake_llm.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    fake_llm.when(r"Question: As a single student, how much money", FUNDS_ANSWER)
    fake_llm.when(r"Question: As a single student, how many hours", {
        "answer": "Up to 24 hours per week.", "source_number": 2, "evidence_quote": WORK})
    fake_llm.when(r"User Question:", "unused")
    return fake_llm


async def run():
    intent_cache.clear()
    trace = TraceRecorder("test", query=QUESTION)
    with activate_trace(trace), routed_as("verified"):
        result = await rp.rag_pipeline.process_query(QUESTION, db=object())
    return result, trace


def evidence_calls(fake):
    return [c for c in fake.calls if c["user_prompt"].startswith("Question: As a single student")
            and "split a user" not in c["system_prompt"]]  # not the decomposition call


@pytest.mark.asyncio
async def test_within_the_budget_every_part_is_checked(scripted):
    result, _ = await run()
    assert len(evidence_calls(scripted)) == 2 and "not_reached" not in result["metrics"]["evidence"]
    assert "time limit" not in result["answer"]


@pytest.mark.asyncio
async def test_past_the_budget_the_checked_part_is_returned_and_the_rest_is_labelled(scripted, monkeypatch):
    monkeypatch.setattr(settings, "VERIFIED_PARTS_BEFORE_SECONDS", -1.0)  # the budget is already used
    result, trace = await run()
    assert len(evidence_calls(scripted)) == 1  # the first part is always answered; the second is never started
    assert "CAD $23,448" in result["answer"]
    assert f"I ran out of time before checking this: {PARTS[1]}" in result["answer"]
    assert result["answer"].count("I reached the time limit for one answer") == 1
    assert result["metrics"]["evidence"]["not_reached"] == 1 and result["metrics"]["evidence"]["verified"] == 1
    assert [v["status"] for v in result["verification"]] == ["verified", "not_reached"]
    statuses = [s["status"] for s in trace.steps if s["name"] == "evidence"]
    assert statuses == ["verified", "not_reached"] and not [s for s in trace.steps if s["name"] == "retry"]


@pytest.mark.asyncio
async def test_a_partial_answer_is_not_stored_in_the_verified_cache(scripted, monkeypatch):
    stored = []

    async def key_for(*_, **__):
        return "k"

    async def get(_):
        return None

    async def put(*args, **__):
        stored.append(args)
        return True

    monkeypatch.setattr(settings, "VERIFIED_CACHE_ENABLED", True)
    for name, fn in (("key_for", key_for), ("get", get), ("put", put)):
        monkeypatch.setattr(verified_cache, name, fn)
    await run()
    assert len(stored) == 1  # a complete answer is stored
    monkeypatch.setattr(settings, "VERIFIED_PARTS_BEFORE_SECONDS", -1.0)
    await run()
    assert len(stored) == 1  # a partial one is not


def test_wording():
    results = [ev.PartResult("A?", "verified", "Yes.", "", 0), ev.PartResult("B?", "not_reached")]
    text = ev.compose(results)
    assert "- I ran out of time before checking this: B?" in text and text.endswith("I'll check them.")
    assert ev.verification(results, [])[1] == {"part": "B?", "retried": False, "status": "not_reached"}
    assert describe({"name": "evidence", "status": "not_reached"}) == "Ran out of time before checking a part"
    assert settings.VERIFIED_PARTS_BEFORE_SECONDS < settings.ANSWER_JOB_BUDGET_SECONDS
