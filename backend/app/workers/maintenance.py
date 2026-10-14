"""
Celery redelivery on Windows (M0.6a, finding 3 of decision 0001).

With acks_late, a task whose worker dies stays in Redis's "unacked" set. Kombu puts such messages back on
their queue only from its event-loop timer, which the solo pool on Windows never runs, so a crashed task
was never retried (measured: still unacked 350 s after a 90 s visibility timeout). This module restores
timed-out messages explicitly:
  - when a worker starts (a restarted worker picks up what the crashed one dropped), and
  - every minute via Celery beat (restore-unacked-messages).
Only messages older than CELERY_VISIBILITY_TIMEOUT_SECONDS are restored, so a task that is still running
is never delivered twice as long as tasks finish within that timeout.
"""

import logging

from celery.signals import worker_ready

from app.core.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_BATCH = 100


def restore_timed_out_messages(connection) -> int:
    """Put unacked messages older than the visibility timeout back on their queues. Returns how many."""
    if connection.transport.driver_type != "redis":
        return 0  # only the Redis transport keeps an "unacked" set (e.g. memory:// in tests has none)
    channel = connection.default_channel
    client = channel.client
    restored = 0
    while True:
        before = client.hlen(channel.unacked_key)
        if not before:
            break
        # interval=1: restore on every call (kombu's default only acts on every 10th call per channel)
        channel.qos.restore_visible(num=_BATCH, interval=1)
        moved = before - client.hlen(channel.unacked_key)
        if moved <= 0:
            break
        restored += moved
    if restored:
        logger.warning(f"[CELERY] restored {restored} task message(s) left unacked by a dead worker")
    return restored


@celery_app.task(name="app.workers.maintenance.restore_unacked_task", ignore_result=True)
def restore_unacked_task() -> int:
    with celery_app.connection_for_write() as connection:
        return restore_timed_out_messages(connection)


@worker_ready.connect
def _restore_when_worker_starts(sender=None, **_):
    try:
        app = getattr(sender, "app", None) or celery_app
        with app.connection_for_write() as connection:
            restore_timed_out_messages(connection)
    except Exception:
        logger.warning("[CELERY] could not restore unacked messages at worker start", exc_info=True)


@celery_app.task(name="app.workers.maintenance.diagnostic_sleep_task")
def diagnostic_sleep_task(run_id: str, seconds: float) -> dict:
    """
    Harmless long task for verifying redelivery and progress end to end (no data is touched): sleeps and
    records each start/finish, with the worker's process id, in the Redis list diagnostic:<run_id>.
    """
    import os
    import time

    import redis

    log_key = f"diagnostic:{run_id}"
    client = redis.Redis.from_url(settings.REDIS_URL)
    client.rpush(log_key, f"start pid={os.getpid()}")
    client.expire(log_key, 3600)
    time.sleep(seconds)
    client.rpush(log_key, f"finish pid={os.getpid()}")
    return {"run_id": run_id, "pid": os.getpid()}
