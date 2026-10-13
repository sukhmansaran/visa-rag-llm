"""
LLM gateway (M0.4): role routing, call accounting, structured output with retry, the call queue,
and the FakeLLM used to test agent logic without Ollama.

Ollama is replaced by an httpx.MockTransport, so these tests exercise the real request/response code.
"""

import asyncio
import json
from typing import List

import httpx
import pytest
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError, LLMStructuredOutputError
from app.services.llm import LLMCallStats, OllamaService, record_llm_calls
from app.services.llm_fake import FakeLLM

OLLAMA_TIMINGS = {
    "prompt_eval_count": 812, "eval_count": 140,
    "load_duration": 50_000_000, "prompt_eval_duration": 4_000_000_000,
    "eval_duration": 20_000_000_000, "total_duration": 24_100_000_000,
}


class SubQuestions(BaseModel):
    sub_questions: List[str] = Field(min_length=1, max_length=4)
    needs_rules: bool


def chat_reply(content: str, **extra) -> dict:
    return {"model": "m", "message": {"role": "assistant", "content": content}, "done": True, **OLLAMA_TIMINGS, **extra}


def make_service(handler) -> OllamaService:
    service = OllamaService()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._get_client = lambda: client
    return service


# ---------------------------------------------------------------- role routing

def test_role_models_fall_back_to_default(monkeypatch):
    service = OllamaService()
    for role in ("planner", "answer", "verifier", "sop"):
        assert service.model_for(role) == settings.OLLAMA_MODEL


def test_role_model_setting_overrides_default(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_VERIFIER", "phi4-mini")
    service = OllamaService()
    assert service.model_for("verifier") == "phi4-mini"
    assert service.model_for("answer") == settings.OLLAMA_MODEL


@pytest.mark.asyncio
async def test_explicit_model_beats_role_setting(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL_ANSWER", "role-model")
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=chat_reply("ok"))

    service = make_service(handler)
    await service.generate_answer("sys", "q", role="answer")
    await service.generate_answer("sys", "q", role="answer", model="explicit-model")
    assert [p["model"] for p in sent] == ["role-model", "explicit-model"]


# ---------------------------------------------------------------- accounting

@pytest.mark.asyncio
async def test_chat_call_records_ollama_timings():
    service = make_service(lambda request: httpx.Response(200, json=chat_reply("answer text")))
    with record_llm_calls() as calls:
        assert await service.generate_answer("sys", "q", role="answer") == "answer text"

    assert len(calls) == 1
    stats = calls[0]
    assert (stats.role, stats.mode, stats.ok) == ("answer", "chat", True)
    assert (stats.prompt_tokens, stats.output_tokens) == (812, 140)
    assert (stats.load_s, stats.prompt_s, stats.generation_s, stats.total_s) == (0.05, 4.0, 20.0, 24.1)
    assert stats.tokens_per_second == 7.0
    assert stats.wall_s >= 0 and stats.queue_wait_s >= 0
    assert stats.as_dict()["tokens_per_second"] == 7.0


@pytest.mark.asyncio
async def test_stream_call_records_timings_from_final_line():
    lines = [
        {"message": {"content": "Hello "}, "done": False},
        {"message": {"content": "world"}, "done": False},
        {"message": {"content": ""}, "done": True, **OLLAMA_TIMINGS},
    ]
    body = "\n".join(json.dumps(line) for line in lines)
    service = make_service(lambda request: httpx.Response(200, text=body))

    with record_llm_calls() as calls:
        chunks = [c async for c in service.generate_answer_stream("sys", "q")]

    assert "".join(chunks) == "Hello world"
    assert calls[0].mode == "stream" and calls[0].ok
    assert (calls[0].prompt_tokens, calls[0].output_tokens) == (812, 140)


@pytest.mark.asyncio
async def test_stream_stopped_early_is_recorded_and_frees_the_slot(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 1)
    body = "\n".join(json.dumps({"message": {"content": f"t{i} "}, "done": False}) for i in range(5))
    service = make_service(lambda request: httpx.Response(200, text=body))

    with record_llm_calls() as calls:
        stream = service.generate_answer_stream("sys", "q")
        assert await stream.__anext__() == "t0 "
        await stream.aclose()

    assert calls[0].ok is False and calls[0].error == "stopped_by_consumer"
    # The slot is free again; a stuck slot would make every later call wait for the queue timeout
    semaphore = service._slots.get()
    assert semaphore is not None and not semaphore.locked()


@pytest.mark.asyncio
async def test_failed_call_is_recorded():
    service = make_service(lambda request: httpx.Response(503, json={}))
    with record_llm_calls() as calls:
        with pytest.raises(AIServiceUnavailableError):
            await service.generate_answer("sys", "q")
    assert calls[0].ok is False and calls[0].error == "503"


@pytest.mark.asyncio
async def test_calls_outside_a_recorder_are_not_collected():
    service = make_service(lambda request: httpx.Response(200, json=chat_reply("x")))
    await service.generate_answer("sys", "q")  # must not fail without a recorder
    with record_llm_calls() as calls:
        pass
    assert calls == []


@pytest.mark.asyncio
async def test_response_without_timings_still_works():
    service = make_service(lambda request: httpx.Response(200, json={"message": {"content": "plain"}}))
    with record_llm_calls() as calls:
        assert await service.generate_answer("sys", "q") == "plain"
    assert calls[0].prompt_tokens is None and calls[0].tokens_per_second is None


# ---------------------------------------------------------------- structured output

@pytest.mark.asyncio
async def test_structured_call_sends_schema_and_validates():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=chat_reply(json.dumps({"sub_questions": ["What funds?"], "needs_rules": True})))

    service = make_service(handler)
    with record_llm_calls() as calls:
        result = await service.structured_call(SubQuestions, "Decompose the question.", "How much money do I need?")

    assert result == SubQuestions(sub_questions=["What funds?"], needs_rules=True)
    assert sent[0]["format"] == SubQuestions.model_json_schema()
    assert sent[0]["options"]["temperature"] == 0.0
    assert sent[0]["stream"] is False
    assert [(c.role, c.mode, c.attempts) for c in calls] == [("planner", "structured", 1)]


@pytest.mark.asyncio
async def test_structured_call_retries_once_with_the_validation_error():
    replies = ['{"sub_questions": [], "needs_rules": "maybe"}',
               json.dumps({"sub_questions": ["a", "b"], "needs_rules": False})]
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=chat_reply(replies[len(sent) - 1]))

    service = make_service(handler)
    with record_llm_calls() as calls:
        result = await service.structured_call(SubQuestions, "sys", "q")

    assert result.sub_questions == ["a", "b"]
    retry_messages = sent[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": replies[0]}
    assert "did not match the required JSON schema" in retry_messages[-1]["content"]
    assert [(c.attempts, c.ok) for c in calls] == [(1, False), (2, True)]


@pytest.mark.asyncio
async def test_structured_call_raises_typed_error_after_all_attempts():
    service = make_service(lambda request: httpx.Response(200, json=chat_reply("not json at all")))
    with pytest.raises(LLMStructuredOutputError) as exc:
        await service.structured_call(SubQuestions, "sys", "q")
    assert exc.value.details["schema"] == "SubQuestions"
    assert exc.value.details["attempts"] == 2


@pytest.mark.asyncio
async def test_structured_call_propagates_service_outage():
    service = make_service(lambda request: httpx.Response(500, json={}))
    with pytest.raises(AIServiceUnavailableError):
        await service.structured_call(SubQuestions, "sys", "q")


# ---------------------------------------------------------------- call queue

@pytest.mark.asyncio
async def test_calls_are_serialized_by_the_concurrency_limit(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 1)
    active = {"now": 0, "max": 0}

    async def handler(request):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return httpx.Response(200, json=chat_reply("ok"))

    service = make_service(handler)
    with record_llm_calls() as calls:
        await asyncio.gather(*(service.generate_answer("sys", f"q{i}") for i in range(3)))

    assert active["max"] == 1
    assert max(c.queue_wait_s for c in calls) >= 0.05  # later calls waited for earlier ones


@pytest.mark.asyncio
async def test_concurrency_limit_allows_parallel_calls_when_raised(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 3)
    active = {"now": 0, "max": 0}

    async def handler(request):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return httpx.Response(200, json=chat_reply("ok"))

    service = make_service(handler)
    await asyncio.gather(*(service.generate_answer("sys", f"q{i}") for i in range(3)))
    assert active["max"] == 3


@pytest.mark.asyncio
async def test_queue_timeout_raises_service_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 1)
    monkeypatch.setattr(settings, "LLM_QUEUE_TIMEOUT_SECONDS", 0.05)
    release = asyncio.Event()

    async def handler(request):
        await release.wait()
        return httpx.Response(200, json=chat_reply("ok"))

    service = make_service(handler)
    first = asyncio.create_task(service.generate_answer("sys", "first"))
    await asyncio.sleep(0.01)
    try:
        with pytest.raises(AIServiceUnavailableError) as exc:
            # wait_for: if queueing ever breaks, fail fast instead of hanging on the blocked handler
            await asyncio.wait_for(service.generate_answer("sys", "second"), timeout=2)
        assert exc.value.details["reason"] == "queue_timeout"
    finally:
        release.set()
    assert await asyncio.wait_for(first, timeout=2) == "ok"


# ---------------------------------------------------------------- FakeLLM

@pytest.mark.asyncio
async def test_fake_llm_scripted_responses():
    fake = FakeLLM()
    fake.when(r"proof of funds", "You need 23,448 CAD [Source 1].")
    fake.when(r"decompose", [{"sub_questions": [], "needs_rules": True},
                             {"sub_questions": ["a"], "needs_rules": True}])

    assert await fake.generate_answer("sys", "How much proof of funds?") == "You need 23,448 CAD [Source 1]."
    streamed = "".join([c async for c in fake.generate_answer_stream("sys", "proof of funds please")])
    assert streamed == "You need 23,448 CAD [Source 1]."
    # First scripted reply fails validation, the second is used (same retry behaviour as the real gateway)
    result = await fake.structured_call(SubQuestions, "Decompose this.", "q")
    assert result.sub_questions == ["a"]
    assert [c["kind"] for c in fake.calls] == ["chat", "stream", "structured", "structured"]


@pytest.mark.asyncio
async def test_fake_llm_unmatched_prompt_fails_loudly():
    with pytest.raises(AssertionError, match="no rule matches"):
        await FakeLLM().generate_answer("sys", "anything")


@pytest.mark.asyncio
async def test_fake_llm_raises_scripted_exceptions():
    fake = FakeLLM().when(r"down", AIServiceUnavailableError("down"))
    with pytest.raises(AIServiceUnavailableError):
        await fake.generate_answer("sys", "service down?")


@pytest.mark.asyncio
async def test_fake_llm_fixture_reaches_modules_that_imported_the_service(fake_llm):
    from app.services import rag_pipeline

    fake_llm.when(r"hours", "Up to 24 hours per week [Source 1].")
    reply = await rag_pipeline.llm_service.generate_answer("sys", "How many hours can I work?")
    assert reply == "Up to 24 hours per week [Source 1]."
    assert fake_llm.calls[0]["role"] == "answer"


@pytest.mark.asyncio
async def test_pipeline_runs_end_to_end_on_the_fake_llm(fake_llm, monkeypatch):
    """Agent-style test: the whole chat pipeline with no Ollama, Chroma or tourist DB."""
    from app.services import rag_pipeline as rp
    from app.services.cache_service import intent_cache

    async def retrieve(**_):
        return [{"text": "Students may work up to 24 hours per week off campus.", "score": 0.85,
                 "authority_tier": 1, "freshness_weight": 1.0,
                 "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work off campus"}}]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    intent_cache.clear()
    fake_llm.when(r"24 hours per week", "You can work up to 24 hours per week off campus [Source 1].")

    result = await rp.rag_pipeline.process_query("How many hours can a study permit holder work off campus?", db=object())

    assert result["answer"].startswith("You can work up to 24 hours per week")
    assert result["metrics"]["source"] == "llm_rag"
    assert fake_llm.calls[0]["role"] == "answer"
    assert "Work off campus" in [s["title"] for s in result["sources"]]


def test_llm_call_stats_tokens_per_second_needs_both_values():
    assert LLMCallStats(role="r", model="m", mode="chat", output_tokens=10).tokens_per_second is None
    assert LLMCallStats(role="r", model="m", mode="chat", output_tokens=10, generation_s=2.0).tokens_per_second == 5.0
