"""
CrawlFrontier: Redis-backed URL priority queue with deduplication.

Manages the URL queue using Redis sorted sets. URLs are scored by
(tier * 1000 + depth) so Tier 1 URLs at any depth are always processed
before Tier 2. Deduplication uses normalized URL comparison.
"""

import json
import fnmatch
from typing import Optional
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

from app.services.crawler.types import FrontierEntry


class CrawlFrontier:
    """Redis-backed URL priority queue with deduplication."""

    def __init__(self, redis_client) -> None:
        """
        Initialize the CrawlFrontier.

        Args:
            redis_client: A redis.asyncio.Redis client instance.
        """
        self.redis = redis_client

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize URL for deduplication.

        - Lowercase the scheme and host
        - Strip fragments (#...)
        - Sort query parameters alphabetically
        - Remove trailing slash (except for root path "/")

        Args:
            url: The URL string to normalize.

        Returns:
            Normalized URL string.
        """
        parsed = urlparse(url)

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Strip fragment
        fragment = ""

        # Sort query parameters alphabetically
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        sorted_query = urlencode(sorted(query_params))

        # Remove trailing slash (except for root path "/")
        path = parsed.path
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        return urlunparse((scheme, netloc, path, parsed.params, sorted_query, fragment))

    @staticmethod
    def compute_priority_score(tier: int, depth: int) -> float:
        """
        Compute priority score for frontier ordering.

        Lower score = higher priority. Tier 1 URLs at any depth are
        always processed before Tier 2.

        Args:
            tier: Data source tier (1-5).
            depth: Crawl depth from seed URL.

        Returns:
            Priority score as float.
        """
        return tier * 1000 + depth

    async def enqueue(
        self,
        url: str,
        depth: int,
        tier: int,
        job_id: str,
        seed_url: str,
        allowed_domains: list[str],
    ) -> bool:
        """
        Add URL to the frontier.

        Validates domain scope, deduplicates via normalized URL,
        and adds to Redis sorted set with priority score.

        Args:
            url: The URL to enqueue.
            depth: Crawl depth of this URL.
            tier: Data source tier (1-5).
            job_id: The crawl job identifier.
            seed_url: The originating seed URL.
            allowed_domains: List of allowed domain glob patterns.

        Returns:
            True if URL was added, False if duplicate or out-of-scope.
        """
        normalized = self.normalize_url(url)
        parsed = urlparse(normalized)
        domain = parsed.netloc

        # Check if domain matches any allowed_domains pattern
        if not any(fnmatch.fnmatch(domain, pattern) for pattern in allowed_domains):
            return False

        # Check if already in the all-URLs set (dedup)
        all_key = f"frontier:{job_id}:all"
        added = await self.redis.sadd(all_key, normalized)
        if added == 0:
            return False

        # Check if already visited
        visited_key = f"frontier:{job_id}:visited"
        if await self.redis.sismember(visited_key, normalized):
            return False

        # Compute priority score and add to sorted set
        score = self.compute_priority_score(tier, depth)
        frontier_key = f"frontier:{job_id}"
        await self.redis.zadd(frontier_key, {normalized: score})

        # Store FrontierEntry data as JSON
        entry = FrontierEntry(
            url=normalized,
            depth=depth,
            tier=tier,
            job_id=job_id,
            seed_url=seed_url,
            allowed_domains=allowed_domains,
        )
        data_key = f"frontier:{job_id}:data:{normalized}"
        await self.redis.set(data_key, json.dumps({
            "url": entry.url,
            "depth": entry.depth,
            "tier": entry.tier,
            "job_id": entry.job_id,
            "seed_url": entry.seed_url,
            "allowed_domains": entry.allowed_domains,
        }))

        return True

    async def dequeue(self, job_id: str) -> Optional[FrontierEntry]:
        """
        Pop the highest-priority URL from the frontier.

        Retrieves the entry with the lowest score (lowest tier, shallowest depth).

        Args:
            job_id: The crawl job identifier.

        Returns:
            FrontierEntry or None if the frontier is empty.
        """
        frontier_key = f"frontier:{job_id}"

        # Pop the member with the lowest score
        result = await self.redis.zpopmin(frontier_key, count=1)
        if not result:
            return None

        normalized_url, _score = result[0]
        # Redis may return bytes
        if isinstance(normalized_url, bytes):
            normalized_url = normalized_url.decode("utf-8")

        # Retrieve entry data
        data_key = f"frontier:{job_id}:data:{normalized_url}"
        raw_data = await self.redis.get(data_key)
        if raw_data is None:
            return None

        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")

        data = json.loads(raw_data)
        return FrontierEntry(
            url=data["url"],
            depth=data["depth"],
            tier=data["tier"],
            job_id=data["job_id"],
            seed_url=data["seed_url"],
            allowed_domains=data["allowed_domains"],
        )

    async def mark_visited(self, url: str, job_id: str) -> None:
        """
        Mark a URL as visited.

        Adds the normalized URL to the visited set and removes it
        from the pending sorted set.

        Args:
            url: The URL to mark as visited.
            job_id: The crawl job identifier.
        """
        normalized = self.normalize_url(url)
        visited_key = f"frontier:{job_id}:visited"
        frontier_key = f"frontier:{job_id}"

        await self.redis.sadd(visited_key, normalized)
        await self.redis.zrem(frontier_key, normalized)

    async def mark_failed(self, url: str, job_id: str, reason: str) -> None:
        """
        Mark a URL as failed.

        Adds the normalized URL to the failed set with the failure reason.

        Args:
            url: The URL that failed.
            job_id: The crawl job identifier.
            reason: The failure reason.
        """
        normalized = self.normalize_url(url)
        failed_key = f"frontier:{job_id}:failed"
        await self.redis.hset(failed_key, normalized, reason)

    async def size(self, job_id: str) -> int:
        """
        Return the number of pending URLs in the frontier.

        Args:
            job_id: The crawl job identifier.

        Returns:
            Number of pending URLs.
        """
        frontier_key = f"frontier:{job_id}"
        return await self.redis.zcard(frontier_key)

    async def is_visited(self, url: str, job_id: str) -> bool:
        """
        Check if a URL has been visited.

        Args:
            url: The URL to check.
            job_id: The crawl job identifier.

        Returns:
            True if the URL has been visited.
        """
        normalized = self.normalize_url(url)
        visited_key = f"frontier:{job_id}:visited"
        return bool(await self.redis.sismember(visited_key, normalized))
