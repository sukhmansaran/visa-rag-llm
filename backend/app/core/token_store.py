"""
Refresh-token revocation store (A3).

Each refresh token carries a unique `jti`. Using a refresh token revokes its jti (rotation),
and presenting a revoked jti is rejected (reuse detection). Logout revokes explicitly.

Backed by Redis so revocations are shared across workers; falls back to a bounded
in-memory set when Redis is unavailable (revocations then apply per process only).
"""

import time
from typing import Dict, Optional

from app.core.config import settings

_KEY_PREFIX = "revoked_jti:"
_REDIS_RETRY_SECONDS = 30
_MAX_MEMORY_ENTRIES = 100_000


class RefreshTokenStore:
    def __init__(self) -> None:
        self._redis = None
        self._redis_retry_at = 0.0
        self._memory: Dict[str, float] = {}  # jti -> expiry epoch seconds

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if time.time() < self._redis_retry_at:
            return None
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5, decode_responses=True
            )
            await client.ping()
            self._redis = client
        except Exception:
            self._redis = None
            self._redis_retry_at = time.time() + _REDIS_RETRY_SECONDS
        return self._redis

    def _prune_memory(self) -> None:
        now = time.time()
        self._memory = {jti: exp for jti, exp in self._memory.items() if exp > now}
        if len(self._memory) > _MAX_MEMORY_ENTRIES:
            # Keep the entries that stay valid longest
            keep = sorted(self._memory.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_MEMORY_ENTRIES]
            self._memory = dict(keep)

    async def revoke(self, jti: str, expires_at: Optional[float]) -> None:
        """Revoke a jti until the token's own expiry (after which it is invalid anyway)."""
        ttl = max(1, int((expires_at or time.time() + 86400 * 30) - time.time()))
        redis_client = await self._get_redis()
        if redis_client:
            try:
                await redis_client.set(f"{_KEY_PREFIX}{jti}", "1", ex=ttl)
                return
            except Exception:
                self._redis = None
                self._redis_retry_at = time.time() + _REDIS_RETRY_SECONDS
        self._memory[jti] = time.time() + ttl
        if len(self._memory) > _MAX_MEMORY_ENTRIES:
            self._prune_memory()

    async def is_revoked(self, jti: str) -> bool:
        redis_client = await self._get_redis()
        if redis_client:
            try:
                return bool(await redis_client.exists(f"{_KEY_PREFIX}{jti}"))
            except Exception:
                self._redis = None
                self._redis_retry_at = time.time() + _REDIS_RETRY_SECONDS
        expiry = self._memory.get(jti)
        return expiry is not None and expiry > time.time()


refresh_token_store = RefreshTokenStore()
