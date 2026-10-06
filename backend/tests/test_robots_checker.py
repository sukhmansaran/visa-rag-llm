"""Unit tests for RobotsChecker."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.crawler.robots import RobotsChecker, ROBOTS_CACHE_TTL


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake async Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def checker(redis_client):
    """Create a RobotsChecker with fake Redis."""
    return RobotsChecker(redis_client)


ROBOTS_ALLOW_ALL = ""

ROBOTS_BLOCK_ADMIN = """\
User-agent: *
Disallow: /admin/
Disallow: /private/
"""

ROBOTS_WITH_DELAY = """\
User-agent: *
Crawl-delay: 10
Disallow: /secret/
"""

ROBOTS_SPECIFIC_AGENT = """\
User-agent: MyBot
Disallow: /no-mybot/

User-agent: *
Disallow: /no-all/
"""


def _mock_httpx_response(text: str, status_code: int = 200):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


class TestIsAllowed:
    """Tests for RobotsChecker.is_allowed."""

    @pytest.mark.asyncio
    async def test_allowed_when_no_robots(self, checker):
        """Empty robots.txt (fetch failure) allows all URLs."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("https://example.com/anything")
            assert result is True

    @pytest.mark.asyncio
    async def test_disallowed_path(self, checker):
        """Disallowed paths return False."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_BLOCK_ADMIN))
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("https://example.com/admin/settings")
            assert result is False

    @pytest.mark.asyncio
    async def test_allowed_path(self, checker):
        """Allowed paths return True."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_BLOCK_ADMIN))
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed("https://example.com/public/page")
            assert result is True

    @pytest.mark.asyncio
    async def test_specific_user_agent_disallowed(self, checker):
        """User-agent-specific rules are respected."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_SPECIFIC_AGENT))
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed(
                "https://example.com/no-mybot/page", user_agent="MyBot"
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_specific_user_agent_allowed_elsewhere(self, checker):
        """MyBot is allowed on paths not in its Disallow."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_SPECIFIC_AGENT))
            mock_client_cls.return_value = mock_client

            result = await checker.is_allowed(
                "https://example.com/public/page", user_agent="MyBot"
            )
            assert result is True


class TestGetCrawlDelay:
    """Tests for RobotsChecker.get_crawl_delay."""

    @pytest.mark.asyncio
    async def test_returns_delay_when_present(self, checker):
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_WITH_DELAY))
            mock_client_cls.return_value = mock_client

            delay = await checker.get_crawl_delay("example.com")
            assert delay == 10.0

    @pytest.mark.asyncio
    async def test_returns_none_when_no_delay(self, checker):
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_BLOCK_ADMIN))
            mock_client_cls.return_value = mock_client

            delay = await checker.get_crawl_delay("example.com")
            assert delay is None

    @pytest.mark.asyncio
    async def test_returns_none_on_fetch_failure(self, checker):
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("timeout"))
            mock_client_cls.return_value = mock_client

            delay = await checker.get_crawl_delay("example.com")
            assert delay is None


class TestFetchRobots:
    """Tests for RobotsChecker._fetch_robots caching behavior."""

    @pytest.mark.asyncio
    async def test_caches_result_in_redis(self, checker, redis_client):
        """Fetched robots.txt is cached in Redis."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_BLOCK_ADMIN))
            mock_client_cls.return_value = mock_client

            await checker._fetch_robots("example.com")

        cached = await redis_client.get("robots:example.com")
        assert cached is not None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        assert "Disallow: /admin/" in cached

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self, checker, redis_client):
        """Second call uses cached value, no HTTP request."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(ROBOTS_BLOCK_ADMIN))
            mock_client_cls.return_value = mock_client

            # First call fetches
            result1 = await checker._fetch_robots("example.com")

        # Second call should use cache (no mock needed)
        result2 = await checker._fetch_robots("example.com")
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_caches_empty_on_failure(self, checker, redis_client):
        """Fetch failure caches empty string."""
        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("404"))
            mock_client_cls.return_value = mock_client

            result = await checker._fetch_robots("missing.com")

        assert result == ""
        cached = await redis_client.get("robots:missing.com")
        assert cached is not None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")
        assert cached == ""

    @pytest.mark.asyncio
    async def test_different_domains_cached_separately(self, checker, redis_client):
        """Each domain gets its own cache entry."""
        robots_a = "User-agent: *\nDisallow: /a/"
        robots_b = "User-agent: *\nDisallow: /b/"

        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(robots_a))
            mock_client_cls.return_value = mock_client
            await checker._fetch_robots("a.com")

        with patch("app.services.crawler.robots.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=_mock_httpx_response(robots_b))
            mock_client_cls.return_value = mock_client
            await checker._fetch_robots("b.com")

        cached_a = await redis_client.get("robots:a.com")
        cached_b = await redis_client.get("robots:b.com")
        if isinstance(cached_a, bytes):
            cached_a = cached_a.decode("utf-8")
        if isinstance(cached_b, bytes):
            cached_b = cached_b.decode("utf-8")
        assert "Disallow: /a/" in cached_a
        assert "Disallow: /b/" in cached_b
