"""Unit tests for ThrottleManager."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
import time

from app.services.crawler.throttle import ThrottleManager, DEFAULT_TIER_RATES


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


DOMAIN = "example.com"


class TestAcquire:
    """Tests for ThrottleManager.acquire."""

    @pytest.mark.asyncio
    async def test_acquire_first_request_succeeds(self, throttle):
        result = await throttle.acquire(DOMAIN)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_blocked_domain_returns_false(self, throttle, redis_client):
        await redis_client.set(f"throttle:{DOMAIN}:blocked", "1")
        result = await throttle.acquire(DOMAIN)
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_paused_domain_returns_false(self, throttle, redis_client):
        await redis_client.set(f"throttle:{DOMAIN}:paused", "1", ex=60)
        result = await throttle.acquire(DOMAIN)
        assert result is False

    @pytest.mark.asyncio
    async def test_acquire_respects_rate_limit(self, throttle):
        # First request should succeed (bucket starts with 1 token)
        assert await throttle.acquire(DOMAIN) is True
        # Immediate second request should fail (no time to refill)
        assert await throttle.acquire(DOMAIN) is False

    @pytest.mark.asyncio
    async def test_acquire_uses_configured_rate(self, throttle, redis_client):
        # Set a very high rate so second request succeeds quickly
        await redis_client.set(f"throttle:{DOMAIN}:rate", "1000.0")
        assert await throttle.acquire(DOMAIN) is True
        # With 1000 rps, even a tiny elapsed time should refill enough
        assert await throttle.acquire(DOMAIN) is True

    @pytest.mark.asyncio
    async def test_acquire_independent_domains(self, throttle):
        domain_a = "a.example.com"
        domain_b = "b.example.com"
        # Both domains should get their first token independently
        assert await throttle.acquire(domain_a) is True
        assert await throttle.acquire(domain_b) is True


class TestWaitAndAcquire:
    """Tests for ThrottleManager.wait_and_acquire."""

    @pytest.mark.asyncio
    async def test_wait_and_acquire_succeeds(self, throttle):
        # Should succeed immediately on first call
        await throttle.wait_and_acquire(DOMAIN)
        # If we get here without timeout, it worked

    @pytest.mark.asyncio
    async def test_wait_and_acquire_raises_on_blocked(self, throttle, redis_client):
        await redis_client.set(f"throttle:{DOMAIN}:blocked", "1")
        with pytest.raises(RuntimeError, match="permanently blocked"):
            await throttle.wait_and_acquire(DOMAIN)


class TestSetRate:
    """Tests for ThrottleManager.set_rate."""

    @pytest.mark.asyncio
    async def test_set_rate_stores_value(self, throttle, redis_client):
        await throttle.set_rate(DOMAIN, 2.5)
        stored = await redis_client.get(f"throttle:{DOMAIN}:rate")
        assert float(stored) == 2.5

    @pytest.mark.asyncio
    async def test_set_rate_overrides_previous(self, throttle, redis_client):
        await throttle.set_rate(DOMAIN, 1.0)
        await throttle.set_rate(DOMAIN, 0.5)
        stored = await redis_client.get(f"throttle:{DOMAIN}:rate")
        assert float(stored) == 0.5


class TestPauseDomain:
    """Tests for ThrottleManager.pause_domain."""

    @pytest.mark.asyncio
    async def test_pause_domain_blocks_acquire(self, throttle):
        await throttle.pause_domain(DOMAIN, duration_seconds=60)
        result = await throttle.acquire(DOMAIN)
        assert result is False

    @pytest.mark.asyncio
    async def test_pause_domain_sets_ttl(self, throttle, redis_client):
        await throttle.pause_domain(DOMAIN, duration_seconds=120)
        ttl = await redis_client.ttl(f"throttle:{DOMAIN}:paused")
        assert 0 < ttl <= 120


class TestBlockDomain:
    """Tests for ThrottleManager.block_domain."""

    @pytest.mark.asyncio
    async def test_block_domain_blocks_acquire(self, throttle):
        await throttle.block_domain(DOMAIN)
        result = await throttle.acquire(DOMAIN)
        assert result is False

    @pytest.mark.asyncio
    async def test_block_domain_is_permanent(self, throttle, redis_client):
        await throttle.block_domain(DOMAIN)
        ttl = await redis_client.ttl(f"throttle:{DOMAIN}:blocked")
        # TTL of -1 means no expiry (permanent)
        assert ttl == -1

    @pytest.mark.asyncio
    async def test_block_domain_causes_wait_and_acquire_to_raise(self, throttle):
        await throttle.block_domain(DOMAIN)
        with pytest.raises(RuntimeError, match="permanently blocked"):
            await throttle.wait_and_acquire(DOMAIN)


class TestDefaultTierRates:
    """Tests for default tier rate constants."""

    def test_tier1_rate(self):
        assert DEFAULT_TIER_RATES[1] == 0.5

    def test_tier2_through_5_rate(self):
        for tier in range(2, 6):
            assert DEFAULT_TIER_RATES[tier] == 1.0
