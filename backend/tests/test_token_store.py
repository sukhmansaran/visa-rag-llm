"""
Refresh-token revocation store (A3): a revocation must never be lost when Redis
availability changes between revoke() and is_revoked().
"""

import time

import pytest

from app.core.token_store import RefreshTokenStore


class _EmptyRedis:
    """A reachable Redis that has never seen the revocation."""

    async def exists(self, key):
        return 0

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis write timed out")


@pytest.mark.asyncio
async def test_revocation_survives_redis_coming_back(monkeypatch):
    store = RefreshTokenStore()
    available = {"redis": None}

    async def fake_get_redis():
        return available["redis"]

    monkeypatch.setattr(store, "_get_redis", fake_get_redis)

    # Revoked while Redis is down, checked once Redis is back (without the key)
    await store.revoke("jti-down", time.time() + 3600)
    available["redis"] = _EmptyRedis()
    assert await store.is_revoked("jti-down")


@pytest.mark.asyncio
async def test_revocation_survives_failed_redis_write(monkeypatch):
    store = RefreshTokenStore()

    async def fake_get_redis():
        return _EmptyRedis()

    monkeypatch.setattr(store, "_get_redis", fake_get_redis)

    await store.revoke("jti-write-failed", time.time() + 3600)
    assert await store.is_revoked("jti-write-failed")
    assert not await store.is_revoked("jti-never-revoked")
