"""Unit tests for CrawlerWorker."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.crawler.throttle import ThrottleManager
from app.services.crawler.worker import (
    CrawlerWorker,
    _DEFAULT_USER_AGENTS,
    _parse_retry_after,
    MAX_RETRIES,
)
from app.services.crawler.types import FetchResult


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake async Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def throttle(redis_client):
    """Create a ThrottleManager with fake Redis."""
    return ThrottleManager(redis_client)


@pytest_asyncio.fixture
async def worker(throttle):
    """Create a CrawlerWorker with no proxy pool."""
    return CrawlerWorker(throttle_manager=throttle)


@pytest_asyncio.fixture
async def worker_with_proxies(throttle):
    """Create a CrawlerWorker with a proxy pool."""
    return CrawlerWorker(
        throttle_manager=throttle,
        proxy_pool=["http://proxy1:8080", "http://proxy2:8080", "http://proxy3:8080"],
    )


class TestRotateUserAgent:
    """Tests for CrawlerWorker._rotate_user_agent."""

    def test_returns_string_from_pool(self, worker):
        ua = worker._rotate_user_agent()
        assert ua in _DEFAULT_USER_AGENTS

    def test_round_robin_cycles(self, worker):
        """Calling N times should cycle through all UAs."""
        pool_size = len(worker._user_agents)
        seen = set()
        for _ in range(pool_size):
            seen.add(worker._rotate_user_agent())
        assert len(seen) == pool_size

    def test_wraps_around(self, worker):
        """After cycling through all UAs, it starts over."""
        pool_size = len(worker._user_agents)
        first = worker._rotate_user_agent()
        for _ in range(pool_size - 1):
            worker._rotate_user_agent()
        wrapped = worker._rotate_user_agent()
        assert wrapped == first

    def test_counter_increments(self, worker):
        assert worker._ua_counter == 0
        worker._rotate_user_agent()
        assert worker._ua_counter == 1
        worker._rotate_user_agent()
        assert worker._ua_counter == 2


class TestGetProxy:
    """Tests for CrawlerWorker._get_proxy."""

    def test_returns_none_without_pool(self, worker):
        assert worker._get_proxy() is None

    def test_returns_proxy_from_pool(self, worker_with_proxies):
        proxy = worker_with_proxies._get_proxy()
        assert proxy in worker_with_proxies.proxy_pool

    def test_round_robin_proxies(self, worker_with_proxies):
        pool = worker_with_proxies.proxy_pool
        for i in range(len(pool)):
            assert worker_with_proxies._get_proxy() == pool[i]

    def test_proxy_wraps_around(self, worker_with_proxies):
        pool = worker_with_proxies.proxy_pool
        for _ in range(len(pool)):
            worker_with_proxies._get_proxy()
        assert worker_with_proxies._get_proxy() == pool[0]


class TestParseRetryAfter:
    """Tests for _parse_retry_after helper."""

    def test_parses_integer_header(self):
        assert _parse_retry_after({"retry-after": "60"}) == 60

    def test_parses_capitalized_header(self):
        assert _parse_retry_after({"Retry-After": "30"}) == 30

    def test_defaults_to_120_when_missing(self):
        assert _parse_retry_after({}) == 120

    def test_defaults_to_120_on_invalid_value(self):
        assert _parse_retry_after({"retry-after": "not-a-number"}) == 120


class TestFetchHttpx:
    """Tests for CrawlerWorker.fetch using httpx (static pages)."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self, worker):
        """Successful fetch returns FetchResult with correct fields."""
        mock_response = httpx.Response(
            200,
            text="<html><body>Hello</body></html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await worker.fetch("https://example.com")

        assert isinstance(result, FetchResult)
        assert result.url == "https://example.com"
        assert result.status_code == 200
        assert result.raw_html == "<html><body>Hello</body></html>"
        assert result.extracted_text is None
        assert result.used_playwright is False
        assert result.fetch_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_403_blocks_domain_and_raises(self, worker, redis_client):
        """HTTP 403 should block the domain via throttle_manager and raise."""
        mock_response = httpx.Response(
            403,
            text="Forbidden",
            headers={},
            request=httpx.Request("GET", "https://blocked.com/page"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await worker.fetch("https://blocked.com/page")

        # Verify domain was blocked
        blocked = await redis_client.exists("throttle:blocked.com:blocked")
        assert blocked

    @pytest.mark.asyncio
    async def test_429_pauses_domain_and_retries(self, worker, redis_client):
        """HTTP 429 should pause the domain and retry."""
        mock_429 = httpx.Response(
            429,
            text="Too Many Requests",
            headers={"retry-after": "60"},
            request=httpx.Request("GET", "https://slow.com/page"),
        )
        mock_200 = httpx.Response(
            200,
            text="<html>OK</html>",
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://slow.com/page"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[mock_429, mock_200])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.services.crawler.worker.asyncio.sleep", new_callable=AsyncMock):
                result = await worker.fetch("https://slow.com/page")

        assert result.status_code == 200
        # Verify domain was paused
        paused = await redis_client.exists("throttle:slow.com:paused")
        assert paused

    @pytest.mark.asyncio
    async def test_429_uses_default_120s_without_retry_after(self, worker, redis_client):
        """HTTP 429 without Retry-After header should pause for 120s."""
        mock_429 = httpx.Response(
            429,
            text="Too Many Requests",
            headers={},
            request=httpx.Request("GET", "https://slow2.com/page"),
        )
        mock_200 = httpx.Response(
            200,
            text="<html>OK</html>",
            headers={},
            request=httpx.Request("GET", "https://slow2.com/page"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[mock_429, mock_200])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.services.crawler.worker.asyncio.sleep", new_callable=AsyncMock):
                result = await worker.fetch("https://slow2.com/page")

        assert result.status_code == 200
        paused_ttl = await redis_client.ttl("throttle:slow2.com:paused")
        assert 0 < paused_ttl <= 120

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self, worker):
        """5xx errors should trigger retries with backoff."""
        mock_500 = httpx.Response(
            500,
            text="Server Error",
            headers={},
            request=httpx.Request("GET", "https://flaky.com/page"),
        )
        mock_200 = httpx.Response(
            200,
            text="<html>OK</html>",
            headers={},
            request=httpx.Request("GET", "https://flaky.com/page"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=[mock_500, mock_200])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.services.crawler.worker.asyncio.sleep", new_callable=AsyncMock):
                result = await worker.fetch("https://flaky.com/page")

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self, worker):
        """Should raise RuntimeError after all retries fail."""
        mock_500 = httpx.Response(
            500,
            text="Server Error",
            headers={},
            request=httpx.Request("GET", "https://down.com/page"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_500)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.services.crawler.worker.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="Failed to fetch"):
                    await worker.fetch("https://down.com/page")

    @pytest.mark.asyncio
    async def test_rotates_user_agent_on_each_attempt(self, worker):
        """Each fetch attempt should use a different user-agent."""
        captured_uas = []

        async def capture_get(url, headers=None, **kwargs):
            captured_uas.append(headers.get("User-Agent"))
            return httpx.Response(
                500, text="Error", headers={},
                request=httpx.Request("GET", url),
            )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=capture_get)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.services.crawler.worker.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError):
                    await worker.fetch("https://example.com")

        # Each retry should have used a different UA (round-robin)
        assert len(captured_uas) == MAX_RETRIES
        assert captured_uas[0] != captured_uas[1]


class TestFetchPlaywright:
    """Tests for CrawlerWorker.fetch with Playwright."""

    @pytest.mark.asyncio
    async def test_playwright_fetch(self, worker):
        """Playwright fetch should return FetchResult with used_playwright=True."""
        with patch.object(
            worker,
            "_fetch_playwright",
            new_callable=AsyncMock,
            return_value={
                "status_code": 200,
                "html": "<html>JS rendered</html>",
                "headers": {"content-type": "text/html"},
            },
        ):
            result = await worker.fetch("https://jssite.com", use_playwright=True)

        assert isinstance(result, FetchResult)
        assert result.status_code == 200
        assert result.raw_html == "<html>JS rendered</html>"
        assert result.used_playwright is True


class TestFetchPdf:
    """Tests for CrawlerWorker.fetch_pdf."""

    @pytest.mark.asyncio
    async def test_fetch_pdf_extracts_text(self, worker):
        """fetch_pdf should download PDF and extract text."""
        # Create a minimal mock for pypdf
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Sample PDF text content"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        mock_response = httpx.Response(
            200,
            content=b"%PDF-1.4 fake pdf bytes",
            headers={"content-type": "application/pdf"},
            request=httpx.Request("GET", "https://example.com/doc.pdf"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("pypdf.PdfReader", return_value=mock_reader):
                result = await worker.fetch_pdf("https://example.com/doc.pdf")

        assert isinstance(result, FetchResult)
        assert result.url == "https://example.com/doc.pdf"
        assert result.status_code == 200
        assert result.extracted_text == "Sample PDF text content"
        assert result.raw_html is None
        assert result.used_playwright is False

    @pytest.mark.asyncio
    async def test_fetch_pdf_multiple_pages(self, worker):
        """fetch_pdf should concatenate text from multiple PDF pages."""
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Page 1 text"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "Page 2 text"

        mock_reader = MagicMock()
        mock_reader.pages = [mock_page1, mock_page2]

        mock_response = httpx.Response(
            200,
            content=b"%PDF-1.4 fake",
            headers={},
            request=httpx.Request("GET", "https://example.com/multi.pdf"),
        )

        with patch("app.services.crawler.worker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("pypdf.PdfReader", return_value=mock_reader):
                result = await worker.fetch_pdf("https://example.com/multi.pdf")

        assert result.extracted_text == "Page 1 text\nPage 2 text"


class TestInit:
    """Tests for CrawlerWorker initialization."""

    def test_default_user_agents_pool_size(self, worker):
        assert len(worker._user_agents) >= 10

    def test_initial_counters_are_zero(self, worker):
        assert worker._ua_counter == 0
        assert worker._proxy_counter == 0

    def test_stores_throttle_manager(self, worker, throttle):
        assert worker.throttle_manager is throttle

    def test_no_proxy_pool_by_default(self, worker):
        assert worker.proxy_pool is None

    def test_stores_proxy_pool(self, worker_with_proxies):
        assert len(worker_with_proxies.proxy_pool) == 3
