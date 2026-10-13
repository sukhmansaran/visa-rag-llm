"""
Admin access to request traces (M0.5, D8: admin API first, admin page in M6).
Traces are already PII-redacted at write time; these endpoints are admin-only.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_admin_user
from app.models.request_trace import RequestTrace

router = APIRouter(prefix="/admin/traces", tags=["Admin"], dependencies=[Depends(get_current_admin_user)])


def _summary(t: RequestTrace) -> Dict[str, Any]:
    return {
        "trace_id": t.trace_id, "created_at": t.created_at.isoformat(), "endpoint": t.endpoint,
        "status": t.status, "source": t.source, "latency_ms": t.latency_ms, "user_id": t.user_id,
        "session_id": t.session_id, "model": t.model, "failed_over": t.failed_over,
        "llm_calls": len(t.llm_calls or []), "error": t.error,
    }


@router.get("")
async def list_traces(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, description="answered | refused | blocked | error"),
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    since: Optional[datetime] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Most recent traces first, with optional filters."""
    query = select(RequestTrace).order_by(desc(RequestTrace.created_at)).limit(limit)
    if status:
        query = query.where(RequestTrace.status == status)
    if user_id is not None:
        query = query.where(RequestTrace.user_id == user_id)
    if session_id:
        query = query.where(RequestTrace.session_id == session_id)
    if since:
        query = query.where(RequestTrace.created_at >= since)
    rows = (await db.execute(query)).scalars().all()
    return {"traces": [_summary(t) for t in rows]}


@router.get("/{trace_id}")
async def get_trace(trace_id: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """One full trace: steps, model calls, versions, redacted question and answer."""
    trace = (await db.execute(select(RequestTrace).where(RequestTrace.trace_id == trace_id))).scalar_one_or_none()
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {
        **_summary(trace),
        "request_id": trace.request_id,
        "versions": {"model_digest": trace.model_digest, "prompt": trace.prompt_version,
                     "rules": trace.rules_version, "knowledge_base": trace.kb_version},
        "steps": trace.steps,
        "llm_calls": trace.llm_calls,
        "query_redacted": trace.query_redacted,
        "answer_redacted": trace.answer_redacted,
    }
