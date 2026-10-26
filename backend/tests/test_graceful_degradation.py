"""M4.7 graceful degradation: each dependency failure is simulated and gives its labelled behaviour, never a 500.
Model down or timing out: an earlier answer, else the official rule figures, else "temporarily unavailable".
Monitor down: answered with code checks only, labelled "partially verified". Redis down: no jobs, so the client
falls back to the direct stream (fast path), which still answers. (Live fetch arrives with M5.3.)"""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError
from app.models.chat_message import ChatMessage
from app.services import answer_jobs as jobs
from app.services import rag_pipeline as rp
from app.services import retrieval as retrieval_module
from app.services.cache_service import intent_cache
from app.services.tracing import TraceRecorder, activate_trace
from app.services.triage import routed_as

RULES_QUESTION = "How many hours can a study permit holder work off campus?"
NO_RULES_QUESTION = "Can I study a short course in Canada without a permit?"
UNCERTAIN = "How can I fake my bank statement to show more money for my study permit?"  # marked uncertain (M4.5)
PAGE = {"text": "Students may work up to 24 hours per week off campus during regular academic sessions.",
        "score": 0.86, "authority_tier": 1, "freshness_weight": 1.0,
        "metadata": {"url": "https://www.canada.ca/work.html", "title": "Work"}}
DOWN = AIServiceUnavailableError("down", details={"reason": "unreachable"})


@pytest.fixture
def pipeline(fake_llm, monkeypatch):
    async def retrieve(*_, **__):
        return [PAGE]

    async def no_tourist(*_):
        return ""

    monkeypatch.setattr(rp.retrieval_service, "retrieve", retrieve)
    monkeypatch.setattr(rp, "get_tourist_context", no_tourist)
    monkeypatch.setattr(settings, "VERIFIED_MAX_ROUNDS", 1)
    intent_cache.clear()
    return fake_llm


def take_ollama_down(fake, monkeypatch):
    """Every model call and the embedding model fail as they do when Ollama isn't running; retrieval is the real
    service, so its embedding call is what fails."""
    async def no_embedding(_):
        raise AIServiceUnavailableError("Cannot connect to Ollama", details={"reason": "embedding_unreachable"})

    monkeypatch.setattr(rp.retrieval_service, "retrieve",
                        retrieval_module.RetrievalService.retrieve.__get__(rp.retrieval_service))
    monkeypatch.setattr(retrieval_module, "embed_text", no_embedding)
    fake._rules.clear()
    fake.when(r".", DOWN)


@pytest.fixture
def ollama_down(pipeline, monkeypatch):
    take_ollama_down(pipeline, monkeypatch)
    return pipeline


async def answer(question, stream=False, path="fast", chat_history=None):
    trace = TraceRecorder("test", query=question)
    with activate_trace(trace), routed_as(path):
        if stream:
            events = [e async for e in rp.rag_pipeline.process_query_stream(question, chat_history=chat_history)]
            done = events[-1]
            result = {"answer": done["full_response"], "sources": done.get("sources", []), "metrics": done["metrics"],
                      "chunks": "".join(e["content"] for e in events if e["type"] == "chunk")}
        else:
            result = await rp.rag_pipeline.process_query(question, chat_history=chat_history, db=object())
    return result, trace


def step(trace, name):
    return next(s for s in trace.steps if s["name"] == name)


# ---------------------------------------------------------------- Ollama down or timing out

@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_model_down_answers_with_the_rule_figures(ollama_down, stream):
    result, trace = await answer(RULES_QUESTION, stream=stream)
    assert result["answer"].startswith(rp.MODEL_UNAVAILABLE_RULES_INTRO)
    assert "24 hours" in result["answer"] and result["sources"]
    assert result["metrics"]["degraded"] == {"model": "unavailable", "fallback": "rules"}
    assert result["metrics"]["source"] == "model_unavailable_rules"
    assert step(trace, "retrieval")["retrieval_error"] == "AIServiceUnavailableError"
    assert step(trace, "degraded")["fallback"] == "rules"


@pytest.mark.asyncio
async def test_model_down_is_not_mistaken_for_missing_sources(ollama_down):
    result, _ = await answer(NO_RULES_QUESTION, stream=True)
    assert result["answer"] != rp.UNVERIFIED_EVIDENCE_REFUSAL
    assert result["answer"] == rp.MODEL_UNAVAILABLE_MESSAGE
    assert result["metrics"]["source"] == "model_unavailable"


@pytest.mark.asyncio
async def test_model_down_with_nothing_to_answer_with_is_a_clear_503_when_not_streaming(ollama_down):
    with pytest.raises(AIServiceUnavailableError) as raised:
        await answer(NO_RULES_QUESTION)
    assert raised.value.message == rp.MODEL_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_model_down_serves_an_earlier_answer_labelled(pipeline, monkeypatch):
    pipeline.when(r"User Question:", "You can work up to 24 hours per week off campus [Source 1].")
    first, _ = await answer(NO_RULES_QUESTION)  # stored in the fast path's answer cache
    assert first["metrics"]["source"] == "llm_rag"
    take_ollama_down(pipeline, monkeypatch)

    fast, _ = await answer(NO_RULES_QUESTION)  # the fast path serves its cache before any model call anyway
    assert fast["metrics"]["source"] == "cache"
    verified, _ = await answer(NO_RULES_QUESTION, path="verified")  # verified: the fast answer beats none
    assert verified["answer"].startswith("You can work up to 24 hours")
    assert verified["answer"].endswith(rp.MODEL_UNAVAILABLE_CACHED_NOTE)
    assert verified["metrics"]["degraded"]["fallback"] == "cached" and verified["sources"]


@pytest.mark.asyncio
async def test_a_verified_answer_timing_out_falls_back(pipeline):
    """The evidence step times out on the verified path: the rule figures, labelled, not an error."""
    pipeline.when(r".", AIServiceUnavailableError("timed out", details={"reason": "timeout"}))
    result, trace = await answer(RULES_QUESTION, path="verified")
    assert result["metrics"]["degraded"]["fallback"] == "rules"
    assert step(trace, "degraded")["reason"] == "timeout"


@pytest.mark.asyncio
async def test_model_stopping_mid_answer_keeps_the_text_and_says_so(pipeline, monkeypatch):
    from app.services.llm import llm_service

    async def half_then_down(**_):
        yield "Students may work up to 24 hours per week. "
        raise DOWN

    monkeypatch.setattr(llm_service, "generate_answer_stream", half_then_down)
    result, _ = await answer(NO_RULES_QUESTION, stream=True)
    assert result["answer"].startswith("Students may work up to 24 hours per week.")
    assert result["answer"].endswith(rp.MODEL_INTERRUPTED_NOTE.strip())
    assert result["metrics"]["degraded"] == {"model": "interrupted"}


def test_the_embedding_service_reports_ollama_down_as_unavailable(monkeypatch):
    import asyncio
    from app.services.embeddings import EmbeddingService

    class Refused(httpx.AsyncClient):
        async def post(self, *_, **__):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", Refused)
    with pytest.raises(AIServiceUnavailableError):
        asyncio.run(EmbeddingService().generate_embedding("hello"))


# ---------------------------------------------------------------- monitor down

@pytest.fixture
def monitor_down(pipeline, monkeypatch):
    monkeypatch.setattr(settings, "MONITOR_ENABLED", True)
    pipeline.when(r"Message:", DOWN)
    pipeline.when(r"User Question:", "You can work up to 24 hours per week off campus [Source 1].")
    return pipeline


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_monitor_down_answers_labelled_partially_verified(monitor_down, stream):
    result, _ = await answer(UNCERTAIN, stream=stream)
    assert result["metrics"]["monitor"]["available"] is False
    assert result["answer"].endswith(rp.MONITOR_UNAVAILABLE_NOTE.strip())
    assert "24 hours" in result["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_an_answer_the_monitor_could_not_check_is_not_cached(monitor_down, stream):
    await answer(UNCERTAIN, stream=stream)
    again, _ = await answer(UNCERTAIN, stream=stream)
    assert again["metrics"]["source"] != "cache"


@pytest.mark.asyncio
async def test_a_verified_answer_with_the_monitor_down_is_labelled(monitor_down):
    monitor_down.when(r"Question: How many hours", {
        "answer": "Students may work up to 24 hours per week off campus.", "source_number": 1,
        "evidence_quote": "Students may work up to 24 hours per week off campus"})
    monitor_down.when(r"Claim:", {"supported": "yes", "reason": "stated"})
    result, _ = await answer(RULES_QUESTION, path="verified")
    assert result["answer"].endswith(rp.MONITOR_UNAVAILABLE_NOTE.strip())


@pytest.mark.asyncio
async def test_with_the_monitor_up_there_is_no_label(pipeline, monkeypatch):
    monkeypatch.setattr(settings, "MONITOR_ENABLED", True)
    pipeline.when(r"Message:", {"category": "immigration", "confidence": 0.9})
    pipeline.when(r"User Question:", "You can work up to 24 hours per week off campus [Source 1].")
    result, _ = await answer(UNCERTAIN)
    assert "Partially verified" not in result["answer"]


# ---------------------------------------------------------------- Redis down

@pytest_asyncio.fixture
async def redis_down(monkeypatch):
    """Redis unreachable for the job store and queue (a closed port; nothing listens there)."""
    await jobs.close_redis()
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:1/0")
    yield
    await jobs.close_redis()


async def login(client, email):
    r = await client.post("/api/v1/auth/signup", json={"email": email, "password": "testpass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_redis_down_refuses_a_job_with_the_fallback_code_and_stores_nothing(client, db_session, redis_down):
    headers = await login(client, "degraded-jobs@example.com")
    r = await client.post("/api/v1/chat/jobs", json={"query": RULES_QUESTION, "sessionId": "s-redis-down"},
                          headers=headers)
    assert r.status_code == 503 and r.json()["detail"]["error_code"] == "JOBS_UNAVAILABLE"
    saved = (await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == "s-redis-down"))).scalars().all()
    assert saved == []  # the client asks the direct stream next; the question must not be stored twice


@pytest.mark.asyncio
async def test_redis_down_the_direct_stream_still_answers(client, pipeline, redis_down):
    pipeline.when(r"User Question:", "You can work up to 24 hours per week off campus [Source 1].")
    headers = await login(client, "degraded-stream@example.com")
    r = await client.post("/api/v1/chat/answer/stream", json={"query": RULES_QUESTION}, headers=headers)
    assert r.status_code == 200
    assert '"type": "done"' in r.text and "24 hours per week" in r.text


@pytest.mark.asyncio
async def test_redis_down_on_other_job_routes_is_a_503_not_a_500(client, redis_down):
    headers = await login(client, "degraded-status@example.com")
    r = await client.get("/api/v1/chat/jobs/some-job", headers=headers)
    assert r.status_code == 503 and r.json()["error_code"] == "REDIS_UNAVAILABLE"
