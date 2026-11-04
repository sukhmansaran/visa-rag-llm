"""
Agent checkpoints (M5.4): where a paused agent waits for the asker's reply.

A paused run is saved by LangGraph's Postgres checkpointer in its own database (AGENT_CHECKPOINT_URL, by default
DATABASE_URL's server with the database `visa_chatbot_agent`), so LangGraph's schema stays out of the app's Alembic
migrations. Nothing waits in memory: the job ends with the question, and the reply starts a new job that loads the
checkpoint, so a resume survives a reconnect and a worker restart.

Threads are named u{user_id}-{unix seconds}-{random}: the owner is checked on resume and on account deletion, and the
age decides retention. The checkpoint holds the agent's state (question, reply, profile, passages), so a thread is
deleted as soon as its run finishes, and an unanswered one after AGENT_CHECKPOINT_RETENTION_HOURS.

If the checkpoint database can't be reached, the agent runs without pausing: its question is shown as the answer and
the reply is a new question (M5.3 behaviour).
"""

import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

AGENT_DATABASE = "visa_chatbot_agent"
_THREAD = re.compile(r"^u(\d+)-(\d+)-[0-9a-f]{12}$")
_ready = False
_override = None  # tests: a saver (InMemorySaver) used instead of Postgres


def checkpoint_dsn() -> str:
    """psycopg connection string for the checkpoint database."""
    if settings.AGENT_CHECKPOINT_URL:
        return re.sub(r"^postgresql\+\w+://", "postgresql://", settings.AGENT_CHECKPOINT_URL)
    base = re.sub(r"^postgresql\+\w+://", "postgresql://", settings.DATABASE_URL)
    return base.rsplit("/", 1)[0] + "/" + AGENT_DATABASE


def new_thread_id(user_id: Optional[int]) -> str:
    return f"u{user_id or 0}-{int(time.time())}-{secrets.token_hex(6)}"


def thread_owner(thread_id: str) -> Optional[int]:
    match = _THREAD.match(thread_id or "")
    return int(match.group(1)) if match else None


def thread_age_seconds(thread_id: str) -> Optional[float]:
    match = _THREAD.match(thread_id or "")
    return time.time() - int(match.group(2)) if match else None


def owned_by(thread_id: str, user_id: Optional[int]) -> bool:
    owner = thread_owner(thread_id)
    return owner is not None and owner == (user_id or 0)


@asynccontextmanager
async def saver() -> AsyncIterator[Optional[Any]]:
    """The checkpointer for one run, or None when the checkpoint database can't be reached (no pausing then)."""
    global _ready
    if _override is not None:
        yield _override
        return
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        manager = AsyncPostgresSaver.from_conn_string(checkpoint_dsn())
        instance = await manager.__aenter__()
    except Exception as e:  # unreachable, missing database, wrong event loop (psycopg refuses Windows' Proactor)
        logger.warning(f"[AGENT] checkpoints unavailable, the agent won't pause: {type(e).__name__}: {e}")
        yield None
        return
    try:
        if not _ready:
            await instance.setup()  # LangGraph's own tables; idempotent
            _ready = True
        yield instance
    finally:
        await manager.__aexit__(None, None, None)


def looks_like_a_new_question(message: str) -> bool:
    """A message after the agent's question that is a question of its own ("What documents do I need for a work
    permit?") is a new question, not the reply: the paused run is left to expire. Replies are usually short answers
    ("four of us", "a PhD in Ontario")."""
    text = " ".join((message or "").split())
    return text.endswith("?") and len(text.split()) >= 6


def pending_resume(last_message: Any, user_id: Optional[int], message: str) -> Optional[str]:
    """
    The paused run `message` replies to, if any: the conversation's last message is the agent's question (its
    metadata names the thread), asked within AGENT_PAUSE_TTL_SECONDS, by a run this user owns, and `message`
    doesn't look like a new question.
    """
    if not (settings.AGENT_LOOP and settings.AGENT_MODE == "on") or last_message is None:
        return None
    if getattr(last_message, "role", None) != "assistant":
        return None
    thread_id = ((getattr(last_message, "message_metadata", None) or {}).get("agent_pause") or {}).get("thread_id")
    if not thread_id or not owned_by(thread_id, user_id):
        return None
    age = thread_age_seconds(thread_id)
    if age is None or age > settings.AGENT_PAUSE_TTL_SECONDS or looks_like_a_new_question(message):
        return None
    return thread_id


async def delete_thread(thread_id: str) -> None:
    try:
        async with saver() as s:
            if s is not None:
                await s.adelete_thread(thread_id)
    except Exception:
        logger.warning("[AGENT] could not delete a finished thread's checkpoints", exc_info=True)


async def _thread_ids(s) -> List[str]:
    if _override is not None:
        return sorted({key[0] if isinstance(key, tuple) else key for key in getattr(s, "storage", {})})
    async with s.conn.cursor() as cur:
        await cur.execute("SELECT DISTINCT thread_id FROM checkpoints")
        return [row["thread_id"] if isinstance(row, dict) else row[0] for row in await cur.fetchall()]


async def purge(max_age_seconds: Optional[float] = None, user_id: Optional[int] = None) -> Dict[str, int]:
    """Delete unanswered threads older than the retention (D7), or every thread of one user (account deletion).
    Threads whose names don't parse are left alone (not ours)."""
    if max_age_seconds is None and user_id is None:
        max_age_seconds = settings.AGENT_CHECKPOINT_RETENTION_HOURS * 3600
    deleted = 0
    async with saver() as s:
        if s is None:
            return {"deleted": 0, "available": 0}
        for thread_id in await _thread_ids(s):
            age = thread_age_seconds(thread_id)
            if age is None:
                continue
            if (user_id is not None and thread_owner(thread_id) == user_id) or (
                    user_id is None and age > max_age_seconds):
                await s.adelete_thread(thread_id)
                deleted += 1
    return {"deleted": deleted, "available": 1}
