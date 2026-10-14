"""
Answer jobs API (M0.6c): start an answer as a background job, follow its progress over SSE (resumable after
a reconnect), check its status, cancel it. Users can only see and control their own jobs; anything else is 404.

SSE format: each event is sent as `id: <stream id>`, `event: <type>`, `data: <json>`. A client that reconnects
sends the last id it received in the `Last-Event-ID` header (or `?after=`) and gets only newer events.
Idle streams send `: heartbeat` comments every SSE_HEARTBEAT_SECONDS so proxies keep them open.
"""

import json
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.chat_schemas import ChatMessage as ChatMessageSchema
from app.core.config import settings
from app.core.database import get_db
from app.core.logging_config import PIIRedactor, get_logger
from app.core.security import get_current_admin_user, get_current_user
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.services import answer_jobs as jobs

logger = get_logger(__name__)
router = APIRouter(tags=["Chat jobs"])

SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


async def _owned_job(job_id: str, user: User) -> Dict[str, str]:
    job = await jobs.get_job(job_id)
    if job is None or job.get("user_id") != str(user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _enqueue_failed(job_id: str) -> HTTPException:
    logger.error(f"[JOB {job_id}] could not be queued", exc_info=True)
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="The answer service is temporarily unavailable. Please retry shortly.")


@router.post("/chat/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_answer_job(
    message: ChatMessageSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Start answering `message` in the background. Follow it at `events_url`."""
    from app.workers.answer_tasks import run_answer_job_task

    session_id = message.sessionId or str(uuid.uuid4())
    history_rows = (await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == current_user.id, ChatMessage.session_id == session_id)
        .order_by(desc(ChatMessage.created_at)).limit(20)
    )).scalars().all()
    chat_history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    db.add(ChatMessage(
        user_id=current_user.id, role="user", content=PIIRedactor.redact(message.query), session_id=session_id,
        message_metadata={"country": message.country, "university": message.university},
    ))
    await db.commit()

    job_id = await jobs.create_job(current_user.id, kind="answer", session_id=session_id)
    try:
        run_answer_job_task.apply_async(
            args=[job_id, current_user.id, message.query,
                  {"country": message.country, "university": message.university}, chat_history, session_id],
            queue="answers",
        )
    except Exception:
        await jobs.set_status(job_id, "error")
        await jobs.publish(job_id, "error", {"reason": "not_queued"})
        raise _enqueue_failed(job_id)

    return {"job_id": job_id, "session_id": session_id, "status": "queued",
            "events_url": f"{settings.API_V1_PREFIX}/chat/jobs/{job_id}/events"}


@router.get("/chat/jobs/{job_id}")
async def get_answer_job(job_id: str, current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    job = await _owned_job(job_id, current_user)
    return {"job_id": job_id, **{k: job.get(k) for k in ("status", "kind", "session_id", "trace_id", "created_at", "updated_at")}}


@router.post("/chat/jobs/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_answer_job(job_id: str, current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    job = await _owned_job(job_id, current_user)
    if job.get("status") in jobs.TERMINAL:
        return {"job_id": job_id, "status": job["status"]}
    await jobs.request_cancel(job_id)
    return {"job_id": job_id, "status": "cancel_requested"}


async def _event_stream(job_id: str, after: str) -> AsyncIterator[str]:
    """Relay the job's events from `after` on; heartbeat while idle; stop after a terminal event."""
    block_ms = max(1, int(settings.SSE_HEARTBEAT_SECONDS * 1000))
    last = after
    while True:
        events = await jobs.read_events(job_id, after_id=last, block_ms=block_ms)
        if not events:
            job = await jobs.get_job(job_id)
            if job is None:  # expired while we waited
                yield f"event: error\ndata: {json.dumps({'reason': 'job_expired'})}\n\n"
                return
            yield ": heartbeat\n\n"
            continue
        for event_id, kind, data in events:
            last = event_id
            yield f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(data, default=str)}\n\n"
            if kind in jobs.TERMINAL:
                return


@router.get("/chat/jobs/{job_id}/events")
async def stream_answer_job_events(
    job_id: str,
    current_user: User = Depends(get_current_user),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    after: Optional[str] = Query(None, description="Resume after this event id (alternative to Last-Event-ID)"),
) -> StreamingResponse:
    await _owned_job(job_id, current_user)
    resume_from = last_event_id or after or "0"
    if resume_from != "0" and not _looks_like_stream_id(resume_from):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid event id")
    return StreamingResponse(_event_stream(job_id, resume_from), media_type="text/event-stream", headers=SSE_HEADERS)


def _looks_like_stream_id(value: str) -> bool:
    millis, _, seq = value.partition("-")
    return millis.isdigit() and (seq == "" or seq.isdigit())


# ---------------------------------------------------------------- admin: scripted long job (M0.6d proof)

class DiagnosticJobRequest(BaseModel):
    seconds: float = Field(240, gt=0, le=1800)
    interval: float = Field(5, gt=0, le=60)


@router.post("/admin/diagnostic-jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_diagnostic_job(
    request: DiagnosticJobRequest, current_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """Start the scripted long job (no data touched) to check streaming, reconnects and cancel end to end."""
    from app.workers.answer_tasks import run_diagnostic_job_task

    job_id = await jobs.create_job(current_user.id, kind="diagnostic")
    try:
        run_diagnostic_job_task.apply_async(args=[job_id, request.seconds, request.interval], queue="answers")
    except Exception:
        await jobs.set_status(job_id, "error")
        raise _enqueue_failed(job_id)
    return {"job_id": job_id, "status": "queued", "events_url": f"{settings.API_V1_PREFIX}/chat/jobs/{job_id}/events"}
