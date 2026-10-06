"""Unit tests for CrawlFrontier."""

import pytest
import pytest_asyncio
import fakeredis.aioredis

from app.services.crawler.frontier import CrawlFrontier


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake async Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def frontier(redis_client):
    """Create a CrawlFrontier with fake Redis."""
    return CrawlFrontier(redis_client)


JOB_ID = "test-job-001"
SEED_URL = "https://example.com/programs"
ALLOWED_DOMAINS = ["*.example.com", "example.com"]


class TestNormalizeUrl:
    """Tests for CrawlFrontier.normalize_url."""

    def test_lowercase_scheme_and_host(self):
        result = CrawlFrontier.normalize_url("HTTPS://Example.COM/path")
        assert result == "https://example.com/path"

    def test_strip_fragment(self):
        result = CrawlFrontier.normalize_url("https://example.com/page#section")
        assert result == "https://example.com/page"

    def test_sort_query_params(self):
        result = CrawlFrontier.normalize_url("https://example.com/search?z=1&a=2&m=3")
        assert result == "https://example.com/search?a=2&m=3&z=1"

    def test_remove_trailing_slash(self):
        result = CrawlFrontier.normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_keep_root_slash(self):
        result = CrawlFrontier.normalize_url("https://example.com/")
        assert result == "https://example.com/"

    def test_idempotent(self):
        url = "HTTPS://Example.COM/path/?b=2&a=1#frag"
        once = CrawlFrontier.normalize_url(url)
        twice = CrawlFrontier.normalize_url(once)
        assert once == twice

    def test_equivalent_urls_normalize_same(self):
        urls = [
            "https://example.com/page?b=2&a=1#frag",
            "HTTPS://EXAMPLE.COM/page?a=1&b=2",
            "https://example.com/page?a=1&b=2#other",
        ]
        normalized = {CrawlFrontier.normalize_url(u) for u in urls}
        assert len(normalized) == 1


class TestComputePriorityScore:
    """Tests for CrawlFrontier.compute_priority_score."""

    def test_tier1_depth0(self):
        assert CrawlFrontier.compute_priority_score(1, 0) == 1000

    def test_tier1_before_tier2(self):
        t1 = CrawlFrontier.compute_priority_score(1, 999)
        t2 = CrawlFrontier.compute_priority_score(2, 0)
        assert t1 < t2

    def test_same_tier_shallower_first(self):
        shallow = CrawlFrontier.compute_priority_score(1, 0)
        deep = CrawlFrontier.compute_priority_score(1, 3)
        assert shallow < deep


class TestEnqueue:
    """Tests for CrawlFrontier.enqueue."""

    @pytest.mark.asyncio
    async def test_enqueue_valid_url(self, frontier):
        result = await frontier.enqueue(
            "https://example.com/programs/cs",
            depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS,
        )
        assert result is True
        assert await frontier.size(JOB_ID) == 1

    @pytest.mark.asyncio
    async def test_enqueue_rejects_out_of_scope_domain(self, frontier):
        result = await frontier.enqueue(
            "https://other-site.org/page",
            depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS,
        )
        assert result is False
        assert await frontier.size(JOB_ID) == 0

    @pytest.mark.asyncio
    async def test_enqueue_deduplicates(self, frontier):
        url = "https://example.com/programs/cs"
        await frontier.enqueue(url, depth=1, tier=1, job_id=JOB_ID,
                               seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        result = await frontier.enqueue(url, depth=1, tier=1, job_id=JOB_ID,
                                        seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        assert result is False
        assert await frontier.size(JOB_ID) == 1

    @pytest.mark.asyncio
    async def test_enqueue_deduplicates_normalized_variants(self, frontier):
        await frontier.enqueue(
            "https://example.com/page?b=2&a=1#frag",
            depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS,
        )
        result = await frontier.enqueue(
            "HTTPS://EXAMPLE.COM/page?a=1&b=2",
            depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_enqueue_rejects_visited_url(self, frontier):
        url = "https://example.com/visited"
        await frontier.mark_visited(url, JOB_ID)
        # Need to add to all set first for the visited check path
        # Actually, enqueue checks visited set after dedup set.
        # Since the URL wasn't in the all set, it gets added there first,
        # then the visited check happens.
        result = await frontier.enqueue(
            url, depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_enqueue_glob_pattern_matching(self, frontier):
        result = await frontier.enqueue(
            "https://sub.example.com/page",
            depth=1, tier=1, job_id=JOB_ID,
            seed_url=SEED_URL, allowed_domains=["*.example.com"],
        )
        assert result is True


class TestDequeue:
    """Tests for CrawlFrontier.dequeue."""

    @pytest.mark.asyncio
    async def test_dequeue_empty_returns_none(self, frontier):
        result = await frontier.dequeue(JOB_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_dequeue_returns_highest_priority(self, frontier):
        # Enqueue tier 2 first, then tier 1
        await frontier.enqueue("https://example.com/t2", depth=0, tier=2,
                               job_id=JOB_ID, seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        await frontier.enqueue("https://example.com/t1", depth=0, tier=1,
                               job_id=JOB_ID, seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)

        entry = await frontier.dequeue(JOB_ID)
        assert entry is not None
        assert entry.url == "https://example.com/t1"
        assert entry.tier == 1

    @pytest.mark.asyncio
    async def test_dequeue_respects_depth_within_tier(self, frontier):
        await frontier.enqueue("https://example.com/deep", depth=3, tier=1,
                               job_id=JOB_ID, seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        await frontier.enqueue("https://example.com/shallow", depth=0, tier=1,
                               job_id=JOB_ID, seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)

        entry = await frontier.dequeue(JOB_ID)
        assert entry.url == "https://example.com/shallow"

    @pytest.mark.asyncio
    async def test_dequeue_returns_frontier_entry(self, frontier):
        await frontier.enqueue("https://example.com/page", depth=2, tier=3,
                               job_id=JOB_ID, seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        entry = await frontier.dequeue(JOB_ID)
        assert entry.url == "https://example.com/page"
        assert entry.depth == 2
        assert entry.tier == 3
        assert entry.job_id == JOB_ID
        assert entry.seed_url == SEED_URL


class TestMarkVisitedAndFailed:
    """Tests for mark_visited, mark_failed, is_visited."""

    @pytest.mark.asyncio
    async def test_mark_visited(self, frontier):
        url = "https://example.com/page"
        await frontier.enqueue(url, depth=0, tier=1, job_id=JOB_ID,
                               seed_url=SEED_URL, allowed_domains=ALLOWED_DOMAINS)
        assert await frontier.size(JOB_ID) == 1

        await frontier.mark_visited(url, JOB_ID)
        assert await frontier.is_visited(url, JOB_ID) is True
        assert await frontier.size(JOB_ID) == 0

    @pytest.mark.asyncio
    async def test_is_visited_false_for_unvisited(self, frontier):
        assert await frontier.is_visited("https://example.com/new", JOB_ID) is False

    @pytest.mark.asyncio
    async def test_mark_failed(self, frontier):
        url = "https://example.com/broken"
        await frontier.mark_failed(url, JOB_ID, "HTTP 500")
        # Verify it's stored in the failed hash
        failed_key = f"frontier:{JOB_ID}:failed"
        normalized = CrawlFrontier.normalize_url(url)
        reason = await frontier.redis.hget(failed_key, normalized)
        if isinstance(reason, bytes):
            reason = reason.decode("utf-8")
        assert reason == "HTTP 500"
