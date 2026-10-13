"""
Regression tests for problem #1: async clients bound to a single event loop.

Celery tasks run each job on a fresh loop (asyncio.run) and pytest-asyncio uses a loop per test.
A module-level httpx/redis client created on one loop fails on the next with
"Event loop is closed". These tests run plain asyncio.run calls back to back, like a worker does.
"""

import asyncio

import httpx

from app.core.loop_local import LoopLocal
from app.services.llm import llm_service
from app.workers.async_runner import run_async


def test_loop_local_keeps_one_instance_per_loop():
    store: LoopLocal = LoopLocal()

    async def grab():
        first = store.get_or_create(object)
        assert store.get_or_create(object) is first  # same loop -> same instance
        return first

    assert asyncio.run(grab()) is not asyncio.run(grab())


def test_llm_client_is_not_reused_across_event_loops():
    async def grab_client():
        return llm_service._get_client()

    first = asyncio.run(grab_client())
    second = asyncio.run(grab_client())
    assert first is not second


def test_run_async_closes_the_loops_llm_client():
    async def use_client():
        return llm_service._get_client()

    client = run_async(use_client())
    assert client.is_closed


def test_sequential_worker_jobs_can_each_call_the_llm(monkeypatch):
    """Back-to-back jobs on fresh loops both succeed (this failed with 'Event loop is closed')."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "ok"}})

    def mock_client_factory(self):
        return self._clients.get_or_create(lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(type(llm_service), "_get_client", mock_client_factory)

    async def job():
        return await llm_service.generate_answer(system_prompt="s", user_prompt="u")

    assert run_async(job()) == "ok"
    assert run_async(job()) == "ok"
    assert run_async(job()) == "ok"


def test_run_async_works_when_a_loop_is_already_running():
    """Eager/nested calls run on a separate thread's loop instead of crashing."""

    async def inner():
        return 42

    async def outer():
        return run_async(inner())

    assert asyncio.run(outer()) == 42
