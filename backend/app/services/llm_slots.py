"""
Machine-wide model slots (2026-10-15 review, B2).

The API process and every Celery worker call the same Ollama, which works on one generation at a time on
this CPU. A per-process queue can't see the other processes, so a chat answer started while another process
was writing an SOP queued *inside* Ollama with no tokens arriving, and its 90 s stream timeout fired before
the first word (reproduced: chat failed after 91 s while an SOP ran). Slots are now taken from Redis, shared
by all processes, *before* the request is sent, so waiting never eats into Ollama timeouts.

Each slot is a lease (sorted-set member scored by its expiry) renewed while the call runs, so a process that
dies frees its slot within LEASE_SECONDS. If Redis is unavailable, acquire() returns None and the caller
falls back to its per-process queue.
"""

import asyncio
import logging
import time
from typing import Optional

from app.core.config import settings
from app.core.loop_local import LoopLocal

logger = logging.getLogger(__name__)

SLOTS_KEY = "llm:slots"
LEASE_SECONDS = 60.0
RENEW_EVERY_SECONDS = 20.0
POLL_SECONDS = 0.2
_REDIS_RETRY_SECONDS = 30.0

# Atomically: drop expired leases, then take a slot if one is free.
_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
    redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
    return 1
end
return 0
"""


class GlobalSlots:
    def __init__(self) -> None:
        self._clients: LoopLocal = LoopLocal()
        self._retry_at = 0.0

    async def _redis(self):
        existing = self._clients.get()
        if existing is not None:
            return existing
        if time.time() < self._retry_at:
            return None
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=2.0)
            await client.ping()
            self._clients.set(client)
            return client
        except Exception:
            self._retry_at = time.time() + _REDIS_RETRY_SECONDS
            logger.warning("[LLM SLOTS] Redis unavailable; using the per-process queue")
            return None

    def _drop_client(self) -> None:
        self._clients.set(None)
        self._retry_at = time.time() + _REDIS_RETRY_SECONDS

    async def acquire(self, token: str, limit: int, timeout: float) -> Optional[bool]:
        """
        Wait for a free slot. True once held; None if Redis is unavailable (caller falls back);
        raises asyncio.TimeoutError if no slot frees up within `timeout` seconds.
        """
        client = await self._redis()
        if client is None:
            return None
        deadline = time.monotonic() + timeout
        while True:
            now = time.time()
            try:
                took = await client.eval(_ACQUIRE, 1, SLOTS_KEY, now, max(1, limit), now + LEASE_SECONDS, token)
            except Exception:
                logger.warning("[LLM SLOTS] Redis error while waiting for a slot; using the per-process queue", exc_info=True)
                self._drop_client()
                return None
            if took:
                return True
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError()
            await asyncio.sleep(POLL_SECONDS)

    async def renew(self, token: str) -> None:
        """Keep a held lease alive (runs in the background for the length of the call)."""
        while True:
            await asyncio.sleep(RENEW_EVERY_SECONDS)
            client = self._clients.get()
            if client is None:
                return
            try:
                await client.zadd(SLOTS_KEY, {token: time.time() + LEASE_SECONDS}, xx=True)
            except Exception:
                logger.warning("[LLM SLOTS] could not renew a slot lease", exc_info=True)

    async def release(self, token: str) -> None:
        client = self._clients.get()
        if client is None:
            return
        try:
            await client.zrem(SLOTS_KEY, token)
        except Exception:
            logger.warning("[LLM SLOTS] could not release a slot (it expires within %ss)", LEASE_SECONDS)

    async def close(self) -> None:
        client = self._clients.pop()
        if client is not None:
            await client.aclose()


global_slots = GlobalSlots()
