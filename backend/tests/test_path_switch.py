"""M1.2 path switch: AGENT_MODE off | shadow | on. Triage decisions are traced; answers never change."""

import pytest

from app.core.config import Settings, settings
from app.services import rag_pipeline as rp
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace

FAST_QUESTION = "How many hours can a study permit holder work off campus?"
VERIFIED_QUESTION = "Can I still get a PGWP if I work off campus more than 24 hours per week?"


@pytest.fixture
def scripted_pipeline(fake_llm, monkeypatch):
    async def retrieve(**_):
        return [{"text": "Students may work up to 24 hours per week off campus.", "score": 0.86,
                 "authority_tier": 1, "freshness_weight": 1.0,
                 "metadata": {"url": "https://www.canada.ca/work-off-campus.html", "title": "Work off campus"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"24 hours per week", "You can work up to 24 hours per week off campus [Source 1].")
    return fake_llm


async def run(question: str, stream: bool):
    intent_cache.clear()  # every run must generate, not replay the previous mode's answer
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace):
        if stream:
            events = [e async for e in rp.rag_pipeline.process_query_stream(question, db=object())]
            done = events[-1]
            answer = {"text": "".join(e["content"] for e in events if e["type"] == "chunk"),
                      "full": done["full_response"], "sources": done.get("sources")}
        else:
            result = await rp.rag_pipeline.process_query(question, db=object())
            answer = {"text": result["answer"], "sources": result.get("sources")}
    metrics = dict((done if stream else result)["metrics"])
    metrics.pop("latency_ms")
    return answer, metrics, [s for s in trace.steps if s["name"] == "triage"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("question", [FAST_QUESTION, VERIFIED_QUESTION])
async def test_answers_are_identical_in_every_mode(scripted_pipeline, monkeypatch, question, stream):
    results = {}
    for mode in ("off", "shadow", "on"):
        monkeypatch.setattr(settings, "AGENT_MODE", mode)
        answer, metrics, _ = await run(question, stream)
        results[mode] = (answer, metrics)
    assert results["off"] == results["shadow"] == results["on"]
    assert "24 hours" in results["off"][0]["text"]


@pytest.mark.asyncio
async def test_off_mode_does_not_triage(scripted_pipeline, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MODE", "off")
    _, _, steps = await run(VERIFIED_QUESTION, stream=False)
    assert steps == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_shadow_mode_traces_the_decision_but_stays_fast(scripted_pipeline, monkeypatch, stream):
    monkeypatch.setattr(settings, "AGENT_MODE", "shadow")
    _, _, steps = await run(VERIFIED_QUESTION, stream)
    assert len(steps) == 1
    step = steps[0]
    assert (step["stage"], step["mode"], step["path"], step["routed"]) == ("question", "shadow", "verified", "fast")
    assert step["reasons"] == ["eligibility"]

    _, _, steps = await run(FAST_QUESTION, stream)
    assert [(s["path"], s["reasons"], s["routed"]) for s in steps] == [("fast", [], "fast")]


@pytest.mark.asyncio
async def test_routed_is_the_path_actually_taken(scripted_pipeline, monkeypatch):
    """`routed` is where the request really runs, not what triage would like: in on mode a verified question
    answered directly (not by a verified job) still ran on the fast path."""
    from app.services.triage import routed_as

    monkeypatch.setattr(settings, "AGENT_MODE", "on")
    _, _, steps = await run(VERIFIED_QUESTION, stream=False)
    assert [(s["path"], s["routed"]) for s in steps] == [("verified", "fast")]
    with routed_as("verified"):  # as the verified answer job runs it
        _, _, steps = await run(VERIFIED_QUESTION, stream=False)
    assert [(s["path"], s["routed"]) for s in steps] == [("verified", "verified")]
    _, _, steps = await run(FAST_QUESTION, stream=False)
    assert [(s["path"], s["routed"]) for s in steps] == [("fast", "fast")]


@pytest.mark.asyncio
@pytest.mark.parametrize("level,expected", [("LOW", ["question", "retrieval"]), ("MEDIUM", ["question"])])
async def test_low_retrieval_confidence_is_traced_after_the_evidence_gate(scripted_pipeline, monkeypatch, level, expected):
    monkeypatch.setattr(settings, "AGENT_MODE", "shadow")
    monkeypatch.setattr(rp.RAGPipeline, "calculate_algorithmic_confidence",
                        staticmethod(lambda chunks, has_tourist_db=False: {"score": 0.4, "level": level}))
    _, _, steps = await run(FAST_QUESTION, stream=False)
    assert [s["stage"] for s in steps] == expected
    if level == "LOW":
        assert (steps[1]["path"], steps[1]["reasons"]) == ("verified", ["low_retrieval"])


@pytest.mark.asyncio
async def test_the_trace_never_carries_the_question(scripted_pipeline, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_MODE", "shadow")
    _, _, steps = await run(VERIFIED_QUESTION, stream=False)
    assert set(steps[0]) == {"name", "ms", "stage", "mode", "path", "reasons", "routed"}


@pytest.mark.parametrize("value,expected", [("Shadow", "shadow"), (" ON ", "on"), ("off", "off"), (None, "shadow")])
def test_agent_mode_setting(value, expected):
    assert Settings(AGENT_MODE=value).AGENT_MODE == expected


def test_agent_mode_rejects_unknown_values():
    with pytest.raises(ValueError):
        Settings(AGENT_MODE="verified")
