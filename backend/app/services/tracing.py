"""
Request traces (M0.5): one record per chat request showing every step, its timing, every model call
and the versions that shaped the answer (principle 11), so a bad answer can be traced to its cause.

    trace = TraceRecorder("chat.answer", user_id=..., session_id=..., query=...)
    with activate_trace(trace):                 # also collects LLM call stats and scopes failover
        with trace_step("retrieval") as step:   # usable from anywhere in the request, e.g. the pipeline
            ...; step["chunks"] = 4
    await save_trace(trace)                      # never raises: a lost trace must not break the answer

Steps hold summaries (counts, scores, verdicts, public URLs), never the user's text. The question and
answer are stored PII-redacted; rows are deleted after TRACE_RETENTION_DAYS (D7).
"""

import contextvars
import hashlib
import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import anyio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging_config import PIIRedactor
from app.core.middleware import request_id_ctx
from app.services.llm import LLMCallStats, _reset, llm_request_scope, llm_service, record_llm_calls

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 2000

# Pipeline metrics["source"] -> trace status
_STATUS_BY_SOURCE = {
    "guardrail_refusal": "blocked",
    "input_guardrail": "blocked",
    "no_evidence_refusal": "refused",
    "insufficient_confidence_refusal": "refused",
}


class TraceRecorder:
    """Collects one request's steps and model calls in memory until save_trace() writes them."""

    def __init__(self, endpoint: str, user_id: Optional[int] = None, session_id: Optional[str] = None, query: str = ""):
        self.trace_id = str(uuid.uuid4())
        self.request_id = request_id_ctx.get()
        self.endpoint = endpoint
        self.user_id = user_id
        self.session_id = session_id
        self.query = query
        self.steps: List[Dict[str, Any]] = []
        self.llm_calls: List[LLMCallStats] = []
        self.scope: Dict[str, Any] = {"failed_over": False}
        self.status = "answered"
        self.source: Optional[str] = None
        self.answer = ""
        self.error: Optional[str] = None
        self.finished = False
        self._started = time.perf_counter()
        self._saved = False

    @contextmanager
    def step(self, name: str, **detail: Any) -> Iterator[Dict[str, Any]]:
        """Time a step; the yielded dict collects summary fields. A step that raises records the error type."""
        record: Dict[str, Any] = dict(detail)
        started = time.perf_counter()
        try:
            yield record
        except BaseException as e:
            record["error"] = type(e).__name__
            raise
        finally:
            self.steps.append({"name": name, "ms": round((time.perf_counter() - started) * 1000, 1), **record})

    def finish(self, answer: str = "", source: Optional[str] = None, status: Optional[str] = None,
               error: Optional[str] = None) -> None:
        """Record how the request ended."""
        self.finished = True
        self.answer = answer or self.answer
        self.source = source or self.source
        if error:
            self.status, self.error = "error", error[:500]
        else:
            self.status = status or _STATUS_BY_SOURCE.get(self.source or "", "answered")

    @property
    def latency_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)


_current: contextvars.ContextVar[Optional[TraceRecorder]] = contextvars.ContextVar("request_trace", default=None)


def current_trace() -> Optional[TraceRecorder]:
    return _current.get()


@contextmanager
def activate_trace(trace: TraceRecorder) -> Iterator[TraceRecorder]:
    """Make `trace` the current request's trace, collect its model calls and scope its failover."""
    token = _current.set(trace)
    try:
        with record_llm_calls() as calls, llm_request_scope() as scope:
            trace.llm_calls, trace.scope = calls, scope
            yield trace
    finally:
        _reset(_current, token)


@contextmanager
def trace_step(name: str, **detail: Any) -> Iterator[Dict[str, Any]]:
    """Record a step on the current trace; a no-op outside a traced request."""
    trace = _current.get()
    if trace is None:
        yield dict(detail)
        return
    with trace.step(name, **detail) as record:
        yield record


def _prompt_version() -> str:
    from app.services.rag_pipeline import GROUNDED_SYSTEM_PROMPT  # local import: the pipeline imports this module
    return hashlib.sha256(GROUNDED_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


async def save_trace(trace: TraceRecorder) -> Optional[str]:
    """Write the trace (redacted). Never raises; returns the trace id, or None if tracing is off or saving failed."""
    if not settings.TRACES_ENABLED or trace._saved:
        return None
    trace._saved = True
    # Shielded: a client disconnect cancels the streaming response, but its trace should still be written
    with anyio.CancelScope(shield=True):
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.request_trace import RequestTrace
            from app.services.rule_engine import get_rules_content_hash
            from app.services.vector_store import vector_store

            model = trace.llm_calls[-1].model if trace.llm_calls else llm_service.model_for("answer")
            try:
                kb_version = await vector_store.content_version()
            except Exception:
                kb_version = None

            row = RequestTrace(
                trace_id=trace.trace_id,
                request_id=(trace.request_id or "")[:64] or None,
                user_id=trace.user_id,
                session_id=(trace.session_id or "")[:64] or None,
                endpoint=trace.endpoint,
                status=trace.status,
                source=trace.source,
                latency_ms=trace.latency_ms,
                model=model,
                model_digest=await llm_service.model_digest(model),
                prompt_version=_prompt_version(),
                rules_version=get_rules_content_hash(),
                kb_version=kb_version,
                failed_over=bool(trace.scope.get("failed_over")) or any(c.failover_from for c in trace.llm_calls),
                steps=trace.steps,
                llm_calls=[c.as_dict() for c in trace.llm_calls],
                query_redacted=PIIRedactor.redact(trace.query or ""),
                answer_redacted=PIIRedactor.redact((trace.answer or "")[:MAX_ANSWER_CHARS]),
                error=trace.error,
            )
            async with AsyncSessionLocal() as session:
                session.add(row)
                await session.commit()
            return trace.trace_id
        except Exception as e:
            logger.warning(f"[TRACE] could not save trace {trace.trace_id}: {type(e).__name__}: {e}")
            return None


async def purge_old_traces(db: AsyncSession, older_than_days: Optional[int] = None) -> int:
    """Delete traces older than the retention period (D7). Returns the number deleted."""
    from app.models.request_trace import RequestTrace

    days = settings.TRACE_RETENTION_DAYS if older_than_days is None else older_than_days
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(delete(RequestTrace).where(RequestTrace.created_at < cutoff))
    await db.commit()
    return result.rowcount or 0
