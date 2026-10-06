"""Unit tests for Deduplicator."""

import pytest
import pytest_asyncio
import fakeredis.aioredis

from app.services.crawler.dedup import Deduplicator


@pytest_asyncio.fixture
async def redis_client():
    """Create a fake async Redis client for testing."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.flushall()
    await client.aclose()


@pytest_asyncio.fixture
async def dedup(redis_client):
    """Create a Deduplicator with fake Redis."""
    return Deduplicator(redis_client)


class TestIsDuplicate:
    """Tests for Deduplicator.is_duplicate."""

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_hash(self, dedup):
        result = await dedup.is_duplicate("abc123")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_after_registration(self, dedup):
        await dedup.register("hash1", "https://example.com/page1")
        result = await dedup.is_duplicate("hash1")
        assert result is True

    @pytest.mark.asyncio
    async def test_different_hashes_are_independent(self, dedup):
        await dedup.register("hash_a", "https://a.example.com")
        assert await dedup.is_duplicate("hash_a") is True
        assert await dedup.is_duplicate("hash_b") is False


class TestRegister:
    """Tests for Deduplicator.register."""

    @pytest.mark.asyncio
    async def test_register_stores_hash(self, dedup, redis_client):
        await dedup.register("hash1", "https://example.com/page1")
        exists = await redis_client.hexists("dedup:hashes", "hash1")
        assert exists

    @pytest.mark.asyncio
    async def test_register_overwrites_url_for_same_hash(self, dedup):
        await dedup.register("hash1", "https://example.com/old")
        await dedup.register("hash1", "https://example.com/new")
        url = await dedup.get_original_url("hash1")
        assert url == "https://example.com/new"

    @pytest.mark.asyncio
    async def test_register_multiple_hashes(self, dedup):
        await dedup.register("h1", "https://example.com/1")
        await dedup.register("h2", "https://example.com/2")
        assert await dedup.is_duplicate("h1") is True
        assert await dedup.is_duplicate("h2") is True


class TestGetOriginalUrl:
    """Tests for Deduplicator.get_original_url."""

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_hash(self, dedup):
        result = await dedup.get_original_url("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_url_after_registration(self, dedup):
        await dedup.register("hash1", "https://example.com/original")
        result = await dedup.get_original_url("hash1")
        assert result == "https://example.com/original"

    @pytest.mark.asyncio
    async def test_returns_string_not_bytes(self, dedup):
        await dedup.register("hash1", "https://example.com/page")
        result = await dedup.get_original_url("hash1")
        assert isinstance(result, str)
