"""
Run async code from synchronous Celery tasks.

Each call gets a fresh event loop (asyncio.run). Async resources are bound to the loop that
created them, so before the loop closes we release the ones this module owns:
  - the loop's Ollama HTTP client (llm_service)
  - the SQLAlchemy async engine's pooled asyncpg connections

Without this, the next task's loop would reuse connections/clients from a closed loop and fail
with "Event loop is closed" / "attached to a different loop".
"""

import asyncio
import concurrent.futures
import logging
import sys
from typing import Any, Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def _release_loop_resources(dispose_engine: bool) -> None:
    from app.services.llm import llm_service

    try:
        await llm_service.close()
    except Exception:
        logger.warning("Failed to close LLM client at end of task loop", exc_info=True)

    if dispose_engine:
        from app.core.database import engine
        try:
            await engine.dispose()
        except Exception:
            logger.warning("Failed to dispose database engine at end of task loop", exc_info=True)


def agent_loop_factory() -> Optional[Callable[[], asyncio.AbstractEventLoop]]:
    """
    Event loop for agent tasks (M0.6a, decision 0001). psycopg's async mode, used by the LangGraph Postgres
    checkpointer, refuses Windows' default ProactorEventLoop, so agent tasks run on a SelectorEventLoop there.
    Code that needs subprocesses (Playwright) must then run on its own thread with a Proactor loop.
    """
    return asyncio.SelectorEventLoop if sys.platform == "win32" else None


def run_async(coro: Awaitable[T], loop_factory: Optional[Callable[[], asyncio.AbstractEventLoop]] = None) -> T:
    """
    Run `coro` to completion on a fresh event loop and clean up loop-bound resources.
    `loop_factory` chooses the loop type (default: asyncio's default; agent tasks pass agent_loop_factory()).
    """

    async def _run(dispose_engine: bool) -> Any:
        try:
            return await coro
        finally:
            await _release_loop_resources(dispose_engine)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal Celery path: no loop running in this thread
        return asyncio.run(_run(dispose_engine=True), loop_factory=loop_factory)

    # Called while a loop is already running in this thread (e.g. eager mode inside the API):
    # run on a separate thread's loop. Don't dispose the engine there, because its pool may
    # hold connections that belong to the caller's loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run(dispose_engine=False), loop_factory=loop_factory).result()
