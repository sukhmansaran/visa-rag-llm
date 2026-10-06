"""
ResponseCache: Redis-backed HTTP response caching.

Caches fetched HTTP responses in Redis to avoid redundant requests
within the same crawl cycle. Supports configurable TTL per entry.
"""

import json
from typing import Optional

from app.services.crawler.types import CachedResponse


class ResponseCache:
    """Redis-backed response cache with configurable TTL."""

    CACHE_PREFIX = "cache:response:"

    def __init__(self, redis_client):
        """Initialize with a Redis client instance."""
        self._redis = redis_client

    def _key(self, url: str) -> str:
        """Build the Redis key for a given URL."""
        return f"{self.CACHE_PREFIX}{url}"

    async def get(self, url: str) -> Optional[CachedResponse]:
        """Get cached response for URL.

        Returns the CachedResponse if found, or None if the key
        does not exist or has expired.
        """
        data = await self._redis.get(self._key(url))
        if data is None:
            return None
        payload = json.loads(data)
        return CachedResponse(
            url=payload["url"],
            status_code=payload["status_code"],
            html=payload["html"],
            headers=payload["headers"],
            cached_at=payload["cached_at"],
        )

    async def put(
        self, url: str, response: CachedResponse, ttl: int = 86400
    ) -> None:
        """Cache a response with TTL (default 24h)."""
        payload = json.dumps({
            "url": response.url,
            "status_code": response.status_code,
            "html": response.html,
            "headers": response.headers,
            "cached_at": response.cached_at,
        })
        await self._redis.set(self._key(url), payload, ex=ttl)

    async def invalidate(self, url: str) -> None:
        """Remove cached response for the given URL."""
        await self._redis.delete(self._key(url))
