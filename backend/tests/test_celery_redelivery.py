"""
M0.6a: a task left unacked by a dead worker is put back on its queue (kombu never does this on Windows
--pool=solo), and agent tasks can run on the event loop psycopg's async mode needs.

The redelivery tests use the real Redis transport (logical db 15, separate from the app's broker db) and
simulate a crash by taking a message without acknowledging it and closing the connection without letting
kombu restore it, which is what happens when the worker process is killed.
"""

import asyncio
import sys
import time
import uuid

import pytest
import redis
from kombu import Connection

from app.core.config import settings
from app.workers.async_runner import agent_loop_factory, run_async
from app.workers.maintenance import restore_timed_out_messages

REDIS_DB15 = settings.REDIS_URL.rsplit("/", 1)[0] + "/15"


def _redis_up() -> bool:
    try:
        return bool(redis.Redis.from_url(REDIS_DB15, socket_connect_timeout=0.5).ping())
    except Exception:
        return False


needs_redis = pytest.mark.skipif(not _redis_up(), reason="Redis not reachable")


def _connection(visibility_timeout: float) -> Connection:
    return Connection(REDIS_DB15, transport_options={"visibility_timeout": visibility_timeout})


def _crash_while_holding_a_message(queue: str, visibility_timeout: float) -> None:
    """Publish one message, take it without acking, then 'die' (no restore on close)."""
    with _connection(visibility_timeout) as conn:
        conn.SimpleQueue(queue).put({"task": "demo"})
    conn = _connection(visibility_timeout)
    q = conn.SimpleQueue(queue)
    message = q.get(timeout=2)
    assert message.payload == {"task": "demo"}
    conn.default_channel.qos.restore_at_shutdown = False  # a killed process restores nothing
    conn.release()


def _queue_length(queue: str) -> int:
    return redis.Redis.from_url(REDIS_DB15).llen(queue)


def _unacked() -> int:
    return redis.Redis.from_url(REDIS_DB15).hlen("unacked")


@pytest.fixture
def clean_db15():
    client = redis.Redis.from_url(REDIS_DB15)
    for key in ("unacked", "unacked_index", "unacked_mutex"):
        client.delete(key)
    yield
    for key in ("unacked", "unacked_index", "unacked_mutex"):
        client.delete(key)


@needs_redis
def test_crashed_workers_message_is_restored_after_the_timeout(clean_db15):
    queue = f"redelivery-{uuid.uuid4().hex[:8]}"
    _crash_while_holding_a_message(queue, visibility_timeout=1)
    assert _queue_length(queue) == 0 and _unacked() == 1  # lost without our restore

    time.sleep(1.5)
    with _connection(visibility_timeout=1) as conn:
        assert restore_timed_out_messages(conn) == 1

    assert _queue_length(queue) == 1 and _unacked() == 0
    with _connection(visibility_timeout=1) as conn:
        q = conn.SimpleQueue(queue)
        message = q.get(timeout=2)
        assert message.payload == {"task": "demo"}  # the same task, delivered again
        message.ack()
    assert _unacked() == 0


@needs_redis
def test_a_message_still_within_its_timeout_is_left_alone(clean_db15):
    """A task that is merely slow (worker alive) must not be delivered twice."""
    queue = f"redelivery-{uuid.uuid4().hex[:8]}"
    _crash_while_holding_a_message(queue, visibility_timeout=600)
    with _connection(visibility_timeout=600) as conn:
        assert restore_timed_out_messages(conn) == 0
    assert _queue_length(queue) == 0 and _unacked() == 1


@needs_redis
def test_restore_handles_many_messages(clean_db15):
    queue = f"redelivery-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        _crash_while_holding_a_message(queue, visibility_timeout=1)
    time.sleep(1.5)
    with _connection(visibility_timeout=1) as conn:
        assert restore_timed_out_messages(conn) == 3
    assert _queue_length(queue) == 3


def test_restore_is_a_no_op_for_non_redis_brokers():
    with Connection("memory://") as conn:
        assert restore_timed_out_messages(conn) == 0


def test_celery_is_configured_to_restore():
    from app.workers.celery_app import celery_app

    celery_app.loader.import_default_modules()
    assert "app.workers.maintenance.restore_unacked_task" in celery_app.tasks
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == settings.CELERY_VISIBILITY_TIMEOUT_SECONDS
    assert celery_app.conf.beat_schedule["restore-unacked-messages"]["schedule"] == 60.0
    # The timeout must exceed the 5-minute answer budget (D3), or a running task would be delivered twice
    assert settings.CELERY_VISIBILITY_TIMEOUT_SECONDS > 300


# ---------------------------------------------------------------- event loops

def _loop_type():
    async def which():
        return type(asyncio.get_running_loop())
    return which()


def test_run_async_uses_the_requested_loop_type():
    assert run_async(_loop_type(), loop_factory=asyncio.SelectorEventLoop) is asyncio.SelectorEventLoop


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific event loop behaviour")
def test_agent_tasks_get_a_selector_loop_on_windows():
    assert agent_loop_factory() is asyncio.SelectorEventLoop
    assert run_async(_loop_type()) is asyncio.ProactorEventLoop  # default stays unchanged for other tasks


@pytest.mark.skipif(sys.platform != "win32", reason="psycopg refuses the Proactor loop only on Windows")
def test_psycopg_async_works_on_the_agent_loop():
    import psycopg

    dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    async def query():
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            return (await (await conn.execute("select 1")).fetchone())[0]

    assert run_async(query(), loop_factory=agent_loop_factory()) == 1
    with pytest.raises(psycopg.InterfaceError):
        run_async(query())  # the default Windows loop is refused: the reason agent_loop_factory exists
