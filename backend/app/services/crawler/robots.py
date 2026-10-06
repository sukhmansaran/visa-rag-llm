"""
RobotsChecker: Robots.txt compliance checker with Redis caching.

Fetches, parses, and caches robots.txt per domain. Uses
urllib.robotparser.RobotFileParser for parsing and Redis for
24-hour caching of parsed rules.
"""

import logging
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

# Cache TTL for robots.txt content: 24 hours
ROBOTS_CACHE_TTL = 86400
# Timeout for fetching robots.txt
ROBOTS_FETCH_TIMEOUT = 5.0


class RobotsChecker:
    """Robots.txt compliance checker with Redis caching."""

    def __init__(self, redis_client) -> None:
        """
        Initialize the RobotsChecker.

        Args:
            redis_client: A redis.asyncio.Redis client instance.
        """
        self.redis = redis_client

    async def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """
        Check if a URL is allowed by the domain's robots.txt rules.

        Extracts the domain from the URL, fetches/caches the robots.txt,
        parses it, and checks if the URL is permitted for the given user_agent.

        If robots.txt fetch fails (404, timeout, etc.), defaults to allowing.

        Args:
            url: The full URL to check.
            user_agent: The user-agent string to check against. Defaults to "*".

        Returns:
            True if the URL is allowed, False if disallowed.
        """
        parsed = urlparse(url)
        domain = parsed.netloc

        robots_content = await self._fetch_robots(domain)

        parser = RobotFileParser()
        parser.parse(robots_content.splitlines())

        return parser.can_fetch(user_agent, url)

    async def get_crawl_delay(
        self, domain: str, user_agent: str = "*"
    ) -> Optional[float]:
        """
        Get the Crawl-delay directive for a domain and user-agent.

        Args:
            domain: The domain to check (e.g. "example.com").
            user_agent: The user-agent string. Defaults to "*".

        Returns:
            The crawl delay in seconds, or None if not specified.
        """
        robots_content = await self._fetch_robots(domain)

        parser = RobotFileParser()
        parser.parse(robots_content.splitlines())

        delay = parser.crawl_delay(user_agent)
        if delay is not None:
            return float(delay)
        return None

    async def _fetch_robots(self, domain: str) -> str:
        """
        Fetch robots.txt content for a domain, with Redis caching.

        Checks Redis cache first (key: robots:{domain}, TTL 24h).
        If not cached, fetches https://{domain}/robots.txt using httpx
        with a 5-second timeout, caches the result, and returns it.

        On any fetch failure (HTTP error, timeout, connection error),
        returns an empty string which allows all URLs.

        Args:
            domain: The domain to fetch robots.txt for (e.g. "example.com").

        Returns:
            The robots.txt content as a string, or empty string on failure.
        """
        cache_key = f"robots:{domain}"

        # Check Redis cache first
        cached = await self.redis.get(cache_key)
        if cached is not None:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            return cached

        # Fetch robots.txt from the domain
        robots_url = f"https://{domain}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=ROBOTS_FETCH_TIMEOUT) as client:
                response = await client.get(robots_url)
                response.raise_for_status()
                content = response.text
        except Exception as exc:
            logger.debug(
                "Failed to fetch robots.txt for %s: %s", domain, exc
            )
            content = ""

        # Cache in Redis with 24h TTL
        await self.redis.set(cache_key, content, ex=ROBOTS_CACHE_TTL)

        return content
