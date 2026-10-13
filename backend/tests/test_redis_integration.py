"""
Integration tests against a real Redis (Memurai on Windows). Skipped when Redis is unreachable (e.g. CI).

Proves the point of running Redis: state is shared across processes and survives restarts,
which the in-memory fallbacks cannot do.
"""

import time
import uuid

import pytest
import redis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings


def _redis_available() -> bool:
    try:
        return bool(redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5).ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _redis_available(), reason="Redis not reachable at REDIS_URL")


def _app_with_rate_limiter():
    from app.core.middleware import RateLimitMiddleware

    app = FastAPI()

    @app.post("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware)
    return app


@pytest.mark.asyncio
async def test_rate_limit_is_shared_across_processes(monkeypatch):
    """Two independent middleware instances (= two uvicorn workers) share one login budget."""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["127.0.0.1"])
    client_ip = f"203.0.113.{uuid.uuid4().int % 250}-{uuid.uuid4().hex[:8]}"  # unique bucket per run
    headers = {"X-Forwarded-For": client_ip}
    worker_a, worker_b = _app_with_rate_limiter(), _app_with_rate_limiter()

    codes = []
    for i in range(12):
        app = worker_a if i % 2 == 0 else worker_b
        transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            codes.append((await client.post("/api/v1/auth/login", headers=headers)).status_code)

    from app.core.middleware import close_rate_limit_redis
    await close_rate_limit_redis()

    # 10/min budget across BOTH workers: requests 11 and 12 are rejected
    assert codes.count(200) == 10
    assert codes.count(429) == 2


@pytest.mark.asyncio
async def test_revoked_refresh_token_is_visible_to_another_process():
    """A revocation written by one RefreshTokenStore is seen by a fresh instance (another worker/restart)."""
    from app.core.token_store import RefreshTokenStore

    jti = f"test-{uuid.uuid4().hex}"
    writer, reader = RefreshTokenStore(), RefreshTokenStore()
    try:
        assert not await reader.is_revoked(jti)
        await writer.revoke(jti, time.time() + 60)
        assert await reader.is_revoked(jti)
        # It really lives in Redis, with an expiry
        raw = redis.Redis.from_url(settings.REDIS_URL)
        assert raw.ttl(f"revoked_jti:{jti}") > 0
    finally:
        await writer.aclose()
        await reader.aclose()
        redis.Redis.from_url(settings.REDIS_URL).delete(f"revoked_jti:{jti}")
