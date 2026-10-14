"""Celery entry points for answer jobs (M0.6b). Logic lives in app/services/answer_jobs.py."""

from typing import Any, Dict, List, Optional

from app.workers.async_runner import agent_loop_factory, run_async
from app.workers.celery_app import celery_app


async def _with_cleanup(coro):
    from app.services.answer_jobs import close_redis

    try:
        return await coro
    finally:
        await close_redis()


@celery_app.task(name="app.workers.answer_tasks.run_answer_job_task")
def run_answer_job_task(job_id: str, user_id: Optional[int], query: str,
                        context_metadata: Optional[Dict[str, Any]] = None,
                        chat_history: Optional[List[Dict[str, Any]]] = None,
                        session_id: Optional[str] = None) -> str:
    from app.services.answer_jobs import execute_answer_job

    return run_async(_with_cleanup(execute_answer_job(job_id, user_id, query, context_metadata, chat_history, session_id)),
                     loop_factory=agent_loop_factory())


@celery_app.task(name="app.workers.answer_tasks.run_diagnostic_job_task")
def run_diagnostic_job_task(job_id: str, seconds: float, interval: float = 5.0) -> str:
    from app.services.answer_jobs import execute_diagnostic_job

    return run_async(_with_cleanup(execute_diagnostic_job(job_id, seconds, interval)), loop_factory=agent_loop_factory())
