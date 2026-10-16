"""
Machine-wide model slots (2026-10-15 review, B2): the API process and the workers share one Ollama, so a
request must wait for a slot *before* it is sent. Uses the real Redis (test db 15); skipped without it.
"""

import asyncio
import json
import time

import httpx
import pytest
import pytest_asyncio
import redis

from app.core.config import settings
from app.core.exceptions import AIServiceUnavailableError
from app.services import llm_slots
from app.services.llm import OllamaService, record_llm_calls


def _redis_up() -> bool:
    try:
        return bool(redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5).ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_up(), reason="Redis not reachable")


@pytest_asyncio.fixture(autouse=True)
async def clean_slots(monkeypatch):
    monkeypatch.setattr(settings, "LLM_GLOBAL_QUEUE", True)
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 1)
    redis.Redis.from_url(settings.REDIS_URL).delete(llm_slots.SLOTS_KEY)
    yield
    await llm_slots.global_slots.close()
    redis.Redis.from_url(settings.REDIS_URL).delete(llm_slots.SLOTS_KEY)


def ollama_with_counter(active: dict, delay: float = 0.15):
    async def handler(request):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(delay)
        active["now"] -= 1
        return httpx.Response(200, json={"message": {"content": "ok"}, "done": True})
    return handler


def service_on(handler) -> OllamaService:
    service = OllamaService()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service._get_client = lambda: client
    return service


@pytest.mark.asyncio
async def test_two_processes_never_generate_at_the_same_time():
    """Separate service instances stand in for the API process and a Celery worker."""
    active = {"now": 0, "max": 0}
    api, worker = service_on(ollama_with_counter(active)), service_on(ollama_with_counter(active))
    with record_llm_calls() as calls:
        await asyncio.gather(*(svc.generate_answer("sys", f"q{i}") for i, svc in enumerate([api, worker, api, worker])))
    assert active["max"] == 1
    assert max(c.queue_wait_s for c in calls) >= 0.15  # later calls waited before being sent
    assert redis.Redis.from_url(settings.REDIS_URL).zcard(llm_slots.SLOTS_KEY) == 0  # all released


@pytest.mark.asyncio
async def test_more_slots_allow_parallel_calls(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 2)
    active = {"now": 0, "max": 0}
    a, b = service_on(ollama_with_counter(active)), service_on(ollama_with_counter(active))
    await asyncio.gather(a.generate_answer("sys", "1"), b.generate_answer("sys", "2"))
    assert active["max"] == 2


@pytest.mark.asyncio
async def test_a_crashed_holders_lease_does_not_block():
    # A process died holding a slot: its lease expired 5 s ago
    redis.Redis.from_url(settings.REDIS_URL).zadd(llm_slots.SLOTS_KEY, {"dead-process": time.time() - 5})
    active = {"now": 0, "max": 0}
    with record_llm_calls() as calls:
        await service_on(ollama_with_counter(active)).generate_answer("sys", "q")
    assert calls[0].ok and calls[0].queue_wait_s < 1


@pytest.mark.asyncio
async def test_a_live_holder_elsewhere_makes_callers_wait_then_time_out(monkeypatch):
    monkeypatch.setattr(settings, "LLM_QUEUE_TIMEOUT_SECONDS", 0.5)
    redis.Redis.from_url(settings.REDIS_URL).zadd(llm_slots.SLOTS_KEY, {"other-process": time.time() + 60})
    sent = []
    service = service_on(lambda request: sent.append(1) or httpx.Response(200, json={"message": {"content": "x"}}))
    with pytest.raises(AIServiceUnavailableError) as exc:
        await service.generate_answer("sys", "q")
    assert exc.value.details["reason"] == "queue_timeout"
    assert sent == []  # never sent to Ollama while the slot was taken


@pytest.mark.asyncio
async def test_leases_are_renewed_during_long_calls(monkeypatch):
    monkeypatch.setattr(llm_slots, "LEASE_SECONDS", 0.6)
    monkeypatch.setattr(llm_slots, "RENEW_EVERY_SECONDS", 0.2)
    scores = []

    async def slow(request):
        for _ in range(4):
            await asyncio.sleep(0.3)
            entries = redis.Redis.from_url(settings.REDIS_URL).zrange(llm_slots.SLOTS_KEY, 0, -1, withscores=True)
            scores.append(entries[0][1] if entries else None)
        return httpx.Response(200, json={"message": {"content": "done"}})

    await service_on(slow).generate_answer("sys", "q")
    assert None not in scores and scores[-1] > scores[0]  # still held after > LEASE_SECONDS, expiry moved forward


@pytest.mark.asyncio
async def test_falls_back_to_the_per_process_queue_without_redis(monkeypatch):
    async def no_redis(self):
        return None
    monkeypatch.setattr(llm_slots.GlobalSlots, "_redis", no_redis)
    active = {"now": 0, "max": 0}
    service = service_on(ollama_with_counter(active))
    await asyncio.gather(*(service.generate_answer("sys", f"q{i}") for i in range(3)))
    assert active["max"] == 1  # still one at a time within this process


@pytest.mark.asyncio
async def test_global_queue_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "LLM_GLOBAL_QUEUE", False)
    redis.Redis.from_url(settings.REDIS_URL).zadd(llm_slots.SLOTS_KEY, {"other-process": time.time() + 60})
    service = service_on(lambda request: httpx.Response(200, json={"message": {"content": "ok"}}))
    assert await service.generate_answer("sys", "q") == "ok"  # ignores the shared slots


@pytest.mark.asyncio
async def test_streams_hold_the_slot_until_they_end():
    lines = "\n".join(json.dumps({"message": {"content": f"w{i} "}, "done": i == 2}) for i in range(3))
    service = service_on(lambda request: httpx.Response(200, text=lines))
    held = []
    async for _ in service.generate_answer_stream("sys", "q"):
        held.append(redis.Redis.from_url(settings.REDIS_URL).zcard(llm_slots.SLOTS_KEY))
    assert held == [1, 1, 1]
    assert redis.Redis.from_url(settings.REDIS_URL).zcard(llm_slots.SLOTS_KEY) == 0


def test_celery_tasks_close_the_slot_client_with_their_loop(monkeypatch):
    """Each Celery task runs on a fresh event loop; its slot client must be closed before the loop ends."""
    from app.workers.async_runner import run_async

    events = []
    real_close = llm_slots.GlobalSlots.close

    async def spy_close(self):
        events.append(("close", self._clients.get() is not None))
        await real_close(self)
        events.append(("closed", self._clients.get() is None))

    monkeypatch.setattr(llm_slots.GlobalSlots, "close", spy_close)

    async def use_a_slot():
        service = service_on(lambda request: httpx.Response(200, json={"message": {"content": "ok"}}))
        return await service.generate_answer("sys", "q")

    assert run_async(use_a_slot()) == "ok"
    assert events == [("close", True), ("closed", True)]  # a live client existed and was closed in the loop
