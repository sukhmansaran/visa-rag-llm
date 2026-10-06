"""Unit tests for ResponseCache."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
import time

from app.services.crawler.cache import ResponseCache
from app.services.crawler.types import CachedResponse


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake async Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def cache(redis_client):
    """Create a ResponseCache with fake Redis."""
    return ResponseCache(redis_client)


def _make_response(url: str = "https://example.com/page") -> CachedResponse:
    """Helper to build a sample CachedResponse."""
    return CachedResponse(
        url=url,
        status_code=200,
        html="<html><body>Hello</body></html>",
        headers={"content-type": "text/html"},
        cached_at=time.time(),
    )


class TestGet:
    """Tests for ResponseCache.get."""

    @pytest.mark.asyncio
    async def test_get_returns_none_when_empty(self, cache):
        result = await cache.get("https://example.com/missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_cached_response(self, cache):
        url = "https://example.com/page"
        resp = _make_response(url)
        await cache.put(url, resp)

        result = await cache.get(url)
        assert result is not None
        assert result.url == resp.url
        assert result.status_code == resp.status_code
        assert result.html == resp.html
        assert result.headers == resp.headers
        assert result.cached_at == resp.cached_at

    @pytest.mark.asyncio
    async def test_get_different_urls_are_independent(self, cache):
        url_a = "https://a.example.com"
        url_b = "https://b.example.com"
        resp_a = _make_response(url_a)
        await cache.put(url_a, resp_a)

        assert await cache.get(url_a) is not None
        assert await cache.get(url_b) is None


class TestPut:
    """Tests for ResponseCache.put."""

    @pytest.mark.asyncio
    async def test_put_stores_response(self, cache, redis_client):
        url = "https://example.com/page"
        resp = _make_response(url)
        await cache.put(url, resp)

        raw = await redis_client.get(f"cache:response:{url}")
        assert raw is not None

    @pytest.mark.asyncio
    async def test_put_sets_ttl(self, cache, redis_client):
        url = "https://example.com/page"
        resp = _make_response(url)
        await cache.put(url, resp, ttl=3600)

        ttl = await redis_client.ttl(f"cache:response:{url}")
        assert 0 < ttl <= 3600

    @pytest.mark.asyncio
    async def test_put_default_ttl_is_24h(self, cache, redis_client):
        url = "https://example.com/page"
        resp = _make_response(url)
        await cache.put(url, resp)

        ttl = await redis_client.ttl(f"cache:response:{url}")
        assert 0 < ttl <= 86400

    @pytest.mark.asyncio
    async def test_put_overwrites_existing(self, cache):
        url = "https://example.com/page"
        resp1 = _make_response(url)
        resp2 = CachedResponse(
            url=url,
            status_code=404,
            html="<html>Not Found</html>",
            headers={},
            cached_at=time.time(),
        )
        await cache.put(url, resp1)
        await cache.put(url, resp2)

        result = await cache.get(url)
        assert result.status_code == 404


class TestInvalidate:
    """Tests for ResponseCache.invalidate."""

    @pytest.mark.asyncio
    async def test_invalidate_removes_entry(self, cache):
        url = "https://example.com/page"
        await cache.put(url, _make_response(url))
        await cache.invalidate(url)

        result = await cache.get(url)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_key_is_noop(self, cache):
        # Should not raise
        await cache.invalidate("https://example.com/never-stored")

    @pytest.mark.asyncio
    async def test_invalidate_only_affects_target_url(self, cache):
        url_a = "https://a.example.com"
        url_b = "https://b.example.com"
        await cache.put(url_a, _make_response(url_a))
        await cache.put(url_b, _make_response(url_b))

        await cache.invalidate(url_a)

        assert await cache.get(url_a) is None
        assert await cache.get(url_b) is not None
