"""M5.2 tool router: deterministic tool choice, measured on labels written before the router (tool_choice_labels.json)."""

import json
from pathlib import Path

import pytest

from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.router import route
from app.services.tracing import TraceRecorder, activate_trace

LABELS = json.loads((Path(__file__).parent / "data" / "tool_choice_labels.json").read_text(encoding="utf-8"))
ALL = [c for split in ("dev", "holdout", "holdout_2", "holdout_3") for c in LABELS[split]]


@pytest.mark.asyncio
async def test_tool_choice_does_not_fall_below_the_measured_level():
    """A regression floor, not the target: 100/114 (88%) when the router was written; the roadmap asks 95%, which
    needs the rule engine to match sections by meaning instead of keywords (see app/services/router.py)."""
    right = [set((await route(c["q"])).tools) == set(c["tools"]) for c in ALL]
    assert sum(right) / len(right) >= 0.87


@pytest.mark.asyncio
async def test_profile_and_processing_times_are_never_chosen_wrongly():
    """The tools the router adds beyond today's pipeline: no false positives on any labelled question."""
    for c in ALL:
        tools = set((await route(c["q"])).tools)
        for tool in ("profile", "processing_times_link"):
            assert tool not in tools or tool in c["tools"], c["q"]


@pytest.mark.asyncio
@pytest.mark.parametrize("question,tools", [
    ("Am I eligible for a PGWP?", ("profile", "rules")),
    ("Based on my background, can I apply for Express Entry?", ("profile", "rules")),
    ("What is the processing time for a study permit?", ("processing_times_link",)),
    ("How long does IRCC take to process a visitor visa?", ("processing_times_link",)),
    ("How much money do I need for a study permit?", ("rules",)),
    ("Will my visa definitely be approved?", ("rules",)),
    ("Is the Student Direct Stream still open?", ("rules",)),
    ("What is maintained status?", ()),
])
async def test_routes(question, tools):
    assert (await route(question)).tools == tools


@pytest.mark.asyncio
async def test_the_route_is_traced_without_the_question(fake_llm, monkeypatch):
    async def retrieve(*_, **__):
        return []

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    fake_llm.when(r"User Question:", "You need CAD $23,448 [Source 1].")
    intent_cache.clear()
    question = "Am I eligible for a study permit with my savings, Priya asks?"
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace):
        await rp.rag_pipeline.process_query(question, db=object())
    step = next(s for s in trace.steps if s["name"] == "route")
    assert step["tools"] == ["profile", "rules"] and step["reasons"] == ["personal"]
    assert "Priya" not in str(step)
