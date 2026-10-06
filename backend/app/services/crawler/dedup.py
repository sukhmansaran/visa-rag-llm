"""
Deduplicator: Redis-backed content hash deduplication.

Uses a Redis hash set to track content hashes and their associated URLs,
enabling fast duplicate detection during active crawl jobs. When a page's
content hash matches an existing entry, the pipeline skips embedding
generation and storage for the duplicate page.
"""

from typing import Optional


class Deduplicator:
    """Content deduplication using Redis hash set."""

    HASH_KEY = "dedup:hashes"

    def __init__(self, redis_client):
        """Initialize with a Redis client instance."""
        self._redis = redis_client

    async def is_duplicate(self, content_hash: str) -> bool:
        """Check if content hash already exists.

        Returns True if the hash is already registered, False otherwise.
        """
        return await self._redis.hexists(self.HASH_KEY, content_hash)

    async def register(self, content_hash: str, url: str) -> None:
        """Register a new content hash with its source URL."""
        await self._redis.hset(self.HASH_KEY, content_hash, url)

    async def get_original_url(self, content_hash: str) -> Optional[str]:
        """Get the URL of the original document for a given hash.

        Returns the URL string if found, or None if the hash is not registered.
        """
        result = await self._redis.hget(self.HASH_KEY, content_hash)
        if result is None:
            return None
        if isinstance(result, bytes):
            return result.decode("utf-8")
        return result
