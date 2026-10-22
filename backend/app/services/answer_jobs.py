"""
Answer jobs (M0.6b): an answer runs as a background job and publishes its progress as events.

Redis keys (all expire after ANSWER_JOB_TTL_SECONDS):
  job:{id}          hash   owner, status (queued | running | done | error | cancelled), path (fast | verified),
                           timestamps, trace_id; verified jobs also queue_position, front_at (M1.4)
  job:{id}:events   stream one entry per event; stream ids only increase, so a reader that reconnects
                           resumes after the last id it saw (the SSE relay in M0.6c)
  job:{id}:cancel   string set to request cancellation

Events: status, queue (verified jobs: place in line, see verified_queue.py), step (each pipeline step as it
finishes), chunk, guardrail_blocked, done, error, cancelled.
The job is cancelled within ~0.5 s of the request, even mid-generation (closing the model stream stops
Ollama), and is stopped at ANSWER_JOB_BUDGET_SECONDS (D3).
"""

import asyncio
import json
import logging
import math
import time
import uuid
from contextlib import aclosing
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.loop_local import LoopLocal

logger = logging.getLogger(__name__)

TERMINAL = {"done", "error", "cancelled"}
_CANCEL_POLL_SECONDS = 0.5
_STREAM_MAXLEN = 5000

_clients: LoopLocal = LoopLocal()


def _redis() -> aioredis.Redis:
    """One client per event loop (Celery tasks and tests run on fresh loops)."""
    return _clients.get_or_create(lambda: aioredis.from_url(settings.REDIS_URL, decode_responses=True))


async def close_redis() -> None:
    client = _clients.pop()
    if client is not None:
        await client.aclose()


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _events_key(job_id: str) -> str:
    return f"job:{job_id}:events"


def _cancel_key(job_id: str) -> str:
    return f"job:{job_id}:cancel"


# ---------------------------------------------------------------- store

async def create_job(user_id: Optional[int], kind: str = "answer", session_id: Optional[str] = None,
                     path: str = "fast") -> str:
    job_id = uuid.uuid4().hex
    key = _job_key(job_id)
    await _redis().hset(key, mapping={
        "user_id": "" if user_id is None else str(user_id), "kind": kind, "status": "queued", "path": path,
        "session_id": session_id or "", "created_at": datetime.utcnow().isoformat(),
    })
    await _redis().expire(key, settings.ANSWER_JOB_TTL_SECONDS)
    return job_id


async def delete_job(job_id: str) -> None:
    """Remove a job that was never started (e.g. refused by the verified-path limits)."""
    await _redis().delete(_job_key(job_id), _events_key(job_id), _cancel_key(job_id))


async def get_job(job_id: str) -> Optional[Dict[str, str]]:
    data = await _redis().hgetall(_job_key(job_id))
    return data or None


async def set_status(job_id: str, status: str, **fields: Any) -> None:
    await _redis().hset(_job_key(job_id), mapping={"status": status, "updated_at": datetime.utcnow().isoformat(),
                                                   **{k: str(v) for k, v in fields.items()}})


async def publish(job_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> str:
    """Append an event; returns its stream id."""
    key = _events_key(job_id)
    event_id = await _redis().xadd(key, {"type": event_type, "data": json.dumps(data or {}, default=str)},
                                   maxlen=_STREAM_MAXLEN, approximate=True)
    await _redis().expire(key, settings.ANSWER_JOB_TTL_SECONDS)
    return event_id


async def read_events(job_id: str, after_id: str = "0", block_ms: Optional[int] = None,
                      count: int = 100) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Events after `after_id`, as (id, type, data). With block_ms, waits that long for new events."""
    if block_ms is None:
        start = "(" + after_id if after_id != "0" else "-"
        entries = await _redis().xrange(_events_key(job_id), min=start, max="+", count=count)
    else:
        result = await _redis().xread({_events_key(job_id): after_id}, count=count, block=block_ms)
        entries = result[0][1] if result else []
    return [(eid, fields.get("type", ""), json.loads(fields.get("data") or "{}")) for eid, fields in entries]


async def request_cancel(job_id: str) -> None:
    await _redis().set(_cancel_key(job_id), "1", ex=settings.ANSWER_JOB_TTL_SECONDS)


async def is_cancel_requested(job_id: str) -> bool:
    return bool(await _redis().exists(_cancel_key(job_id)))


# ---------------------------------------------------------------- running a job

class _Publisher:
    """Publishes events in order from a queue, so synchronous callbacks (trace steps) can emit events live."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None

    def emit(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._queue.put_nowait((event_type, data))

    async def __aenter__(self) -> "_Publisher":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *exc) -> None:
        self._queue.put_nowait(None)
        await self._task

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            try:
                await publish(self.job_id, *item)
            except Exception:
                logger.warning(f"[JOB {self.job_id}] could not publish {item[0]} event", exc_info=True)


async def _run_cancellable(job_id: str, work) -> str:
    """Run `work` (a coroutine); returns "done", "cancelled" or "time_budget"."""
    task = asyncio.create_task(work)

    async def watch_cancel():
        while not task.done():
            if await is_cancel_requested(job_id):
                task.cancel()
                return True
            await asyncio.sleep(_CANCEL_POLL_SECONDS)
        return False

    watcher = asyncio.create_task(watch_cancel())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=settings.ANSWER_JOB_BUDGET_SECONDS)
        return "done"
    except asyncio.TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return "time_budget"
    except asyncio.CancelledError:
        if watcher.done() and watcher.result():
            return "cancelled"
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


async def execute_answer_job(job_id: str, user_id: Optional[int], query: str,
                             context_metadata: Optional[Dict[str, Any]] = None,
                             chat_history: Optional[List[Dict[str, Any]]] = None,
                             session_id: Optional[str] = None, path: str = "fast") -> str:
    """Run the chat pipeline for a job, publishing progress. Returns the final status."""
    if path != "verified":
        return await _execute_answer_job(job_id, user_id, query, context_metadata, chat_history, session_id)

    # Verified path (M1.4): leave the line, run with low model-call priority, then free the user's place.
    # Until M2 the verified path runs today's pipeline.
    from app.services import verified_queue
    from app.services.llm import llm_priority
    from app.services.triage import VERIFIED, routed_as

    started = time.monotonic()
    final = None
    try:
        current = await get_job(job_id)
        if not (current and current.get("status") in TERMINAL):
            await verified_queue.started(job_id)
        with llm_priority("low"), routed_as(VERIFIED):
            final = await _execute_answer_job(job_id, user_id, query, context_metadata, chat_history, session_id)
        return final
    finally:
        # Only finished answers teach the wait estimate (a job cancelled before it started took no time)
        await verified_queue.finished(job_id, user_id, seconds=time.monotonic() - started if final == "done" else None)


async def _execute_answer_job(job_id: str, user_id: Optional[int], query: str,
                              context_metadata: Optional[Dict[str, Any]],
                              chat_history: Optional[List[Dict[str, Any]]],
                              session_id: Optional[str]) -> str:
    from app.services.rag_pipeline import rag_pipeline
    from app.services.tracing import TraceRecorder, activate_trace, save_trace

    trace = TraceRecorder("chat.job", user_id=user_id, session_id=session_id, query=query)
    result: Dict[str, Any] = {"answer": "", "sources": [], "metrics": {}}

    async with _Publisher(job_id) as events:
        current = await get_job(job_id)
        if current and current.get("status") in TERMINAL:
            return current["status"]  # already ended (e.g. given up as not_started): don't add a second ending
        if await is_cancel_requested(job_id):
            events.emit("cancelled", {})
            await set_status(job_id, "cancelled")
            return "cancelled"

        await set_status(job_id, "running", trace_id=trace.trace_id)
        events.emit("status", {"status": "running", "trace_id": trace.trace_id})
        trace.on_step = lambda step: events.emit("step", step)

        async def work():
            async with aclosing(rag_pipeline.process_query_stream(
                query=query, context_metadata=context_metadata, chat_history=chat_history, db=None,
            )) as stream:
                async for event in stream:
                    kind = event.get("type")
                    if kind == "chunk":
                        result["answer"] += event.get("content", "")
                        events.emit("chunk", {"content": event.get("content", "")})
                    elif kind == "guardrail_blocked":
                        events.emit("guardrail_blocked", {k: v for k, v in event.items() if k != "type"})
                    elif kind == "done":
                        result["sources"] = event.get("sources", [])
                        result["metrics"] = event.get("metrics", {})
                        result["answer"] = event.get("full_response", result["answer"])

        with activate_trace(trace):
            try:
                outcome = await _run_cancellable(job_id, work())
            except Exception as e:
                logger.error(f"[JOB {job_id}] failed: {e}", exc_info=True)
                trace.finish(error=type(e).__name__)
                events.emit("error", {"reason": type(e).__name__, "trace_id": trace.trace_id})
                await set_status(job_id, "error")
                await save_trace(trace)
                return "error"

        if outcome == "done":
            metrics = {**result["metrics"], "trace_id": trace.trace_id}
            trace.finish(answer=result["answer"], source=metrics.get("source"))
            await _save_assistant_message(user_id, session_id, query, result["answer"], result["sources"], metrics)
            events.emit("done", {"full_response": result["answer"], "sources": result["sources"], "metrics": metrics})
            final = "done"
        elif outcome == "cancelled":
            trace.finish(answer=result["answer"], status="cancelled")
            events.emit("cancelled", {"partial": result["answer"], "trace_id": trace.trace_id})
            final = "cancelled"
        else:
            trace.finish(answer=result["answer"], error="time_budget")
            events.emit("error", {"reason": "time_budget", "budget_seconds": settings.ANSWER_JOB_BUDGET_SECONDS,
                                  "partial": result["answer"], "trace_id": trace.trace_id})
            final = "error"
        await set_status(job_id, final)
    await save_trace(trace)
    return final


async def _save_assistant_message(user_id: Optional[int], session_id: Optional[str], query: str, answer: str,
                                  sources: List[Dict[str, Any]], metrics: Dict[str, Any]) -> None:
    if user_id is None:
        return
    from app.core.database import AsyncSessionLocal
    from app.core.logging_config import PIIRedactor
    from app.models.chat_message import ChatMessage

    async with AsyncSessionLocal() as db:
        # The user's own PII echoed back by the model isn't stored (B6); the live answer is unchanged
        db.add(ChatMessage(user_id=user_id, role="assistant", content=PIIRedactor.redact_echoes(answer, query),
                           sources={"citations": sources} if sources else {},
                           confidence=float(metrics.get("confidence", 0.0) or 0.0),
                           message_metadata=metrics, session_id=session_id))
        await db.commit()


async def execute_diagnostic_job(job_id: str, seconds: float, interval: float = 5.0) -> str:
    """
    Scripted long job for end-to-end checks (M0.6 done-criterion: a 4-minute job streams to the browser,
    survives a reconnect and can be cancelled). Emits one step every `interval` seconds; touches no data.
    """
    async with _Publisher(job_id) as events:
        current = await get_job(job_id)
        if current and current.get("status") in TERMINAL:
            return current["status"]
        await set_status(job_id, "running")
        events.emit("status", {"status": "running"})

        steps = max(1, math.ceil(seconds / interval))  # a fixed count, so timing jitter can't add a step

        async def work():
            started = time.monotonic()
            for n in range(1, steps + 1):
                await asyncio.sleep(interval)
                events.emit("step", {"name": "diagnostic", "n": n, "of": steps,
                                     "elapsed_s": round(time.monotonic() - started, 1)})
            events.emit("chunk", {"content": f"Diagnostic job finished after {steps} steps."})

        outcome = await _run_cancellable(job_id, work())
        final = {"done": "done", "cancelled": "cancelled"}.get(outcome, "error")
        events.emit({"done": "done", "cancelled": "cancelled"}.get(outcome, "error"),
                    {"reason": outcome} if final == "error" else {})
        await set_status(job_id, final)
    return final
