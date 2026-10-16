"""
Unit tests for RateLimitMiddleware (A1).
Verifies:
1. Health endpoint bypass.
2. Route-specific limits (10 for login, 20 for LLM, 60 default).
3. 429 response structure with Retry-After header.
4. Token-based identification and bounded memory tracking.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.middleware import RateLimitMiddleware


@pytest.fixture
def test_app(monkeypatch):
    # Force the in-memory window so counters never leak between tests via a shared Redis
    async def _no_redis(self):
        return None
    monkeypatch.setattr(RateLimitMiddleware, "_get_redis", _no_redis)
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "fake"}

    @app.post("/api/v1/chat/answer")
    async def chat_answer():
        return {"answer": "fake"}

    @app.get("/api/v1/data")
    async def get_data():
        return {"data": "ok"}

    return app


@pytest.mark.asyncio
async def test_health_bypasses_rate_limit(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Request health endpoint 15 times - should never be 429
        for _ in range(15):
            res = await client.get("/health")
            assert res.status_code == 200


@pytest.mark.asyncio
async def test_login_rate_limit_capped_at_10(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Login is capped at 10 req/min
        for i in range(10):
            res = await client.post("/api/v1/auth/login")
            assert res.status_code == 200

        # 11th request must return 429 Too Many Requests
        res = await client.post("/api/v1/auth/login")
        assert res.status_code == 429
        data = res.json()
        assert data["error_code"] == "RATE_LIMIT_ERROR"
        assert res.headers.get("retry-after") == "60"


@pytest.mark.asyncio
async def test_verified_user_tokens_get_separate_buckets(test_app):
    from app.core.security import create_access_token
    token_a = create_access_token({"sub": "1"})
    token_b = create_access_token({"sub": "2"})
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        for _ in range(20):
            res = await client.post("/api/v1/chat/answer", headers={"Authorization": f"Bearer {token_a}"})
            assert res.status_code == 200
        res = await client.post("/api/v1/chat/answer", headers={"Authorization": f"Bearer {token_a}"})
        assert res.status_code == 429

        # A different *verified* user has their own bucket
        res = await client.post("/api/v1/chat/answer", headers={"Authorization": f"Bearer {token_b}"})
        assert res.status_code == 200


@pytest.mark.asyncio
async def test_forged_tokens_fall_back_to_ip_bucket(test_app):
    """N1: rotating unverifiable tokens must not grant fresh buckets."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        codes = [
            (await client.post("/api/v1/chat/answer", headers={"Authorization": f"Bearer forged-{i}"})).status_code
            for i in range(25)
        ]
    assert codes.count(429) == 5


@pytest.mark.asyncio
async def test_login_bucket_ignores_tokens(test_app):
    """N1: the auth bucket is keyed by IP even when a valid token is presented."""
    from app.core.security import create_access_token
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        codes = [
            (await client.post(
                "/api/v1/auth/login",
                headers={"Authorization": f"Bearer {create_access_token({'sub': str(i)})}"},
            )).status_code
            for i in range(12)
        ]
    assert codes.count(429) == 2


@pytest.mark.asyncio
async def test_untrusted_x_forwarded_for_is_ignored(test_app):
    """N1: X-Forwarded-For from an untrusted peer cannot rotate the client identity."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        codes = [
            (await client.post("/api/v1/auth/login", headers={"X-Forwarded-For": f"203.0.113.{i}"})).status_code
            for i in range(12)
        ]
    assert codes.count(429) == 2


@pytest.mark.asyncio
async def test_trusted_proxy_x_forwarded_for_is_honoured(test_app, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", ["127.0.0.1"])
    transport = ASGITransport(app=test_app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            assert (await client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "198.51.100.7"})).status_code == 200
        assert (await client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "198.51.100.7"})).status_code == 429
        # A different real client behind the same proxy is tracked separately
        assert (await client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "198.51.100.8"})).status_code == 200


@pytest.fixture
def model_app(monkeypatch):
    async def _no_redis(self):
        return None
    monkeypatch.setattr(RateLimitMiddleware, "_get_redis", _no_redis)
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)

    for path in ("/api/v1/chat/jobs", "/api/v1/documents/sop/generate", "/api/v1/tour-packages/create"):
        app.add_api_route(path, lambda: {"ok": True}, methods=["POST"])
    app.add_api_route("/api/v1/chat/jobs/{job_id}/events", lambda job_id: {"ok": True}, methods=["GET"])
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/chat/jobs", "/api/v1/documents/sop/generate", "/api/v1/tour-packages/create"])
async def test_model_call_endpoints_use_the_strict_bucket(model_app, path):
    """Review 2026-10-15: these start minutes of CPU work but fell under the 60/min default."""
    from app.core.security import create_access_token
    headers = {"Authorization": f"Bearer {create_access_token({'sub': '7'})}"}
    async with AsyncClient(transport=ASGITransport(app=model_app), base_url="http://test") as client:
        codes = [(await client.post(path, headers=headers)).status_code for _ in range(22)]
    assert codes.count(200) == 20 and codes.count(429) == 2


@pytest.mark.asyncio
async def test_job_event_reconnects_do_not_spend_the_model_budget(model_app):
    from app.core.security import create_access_token
    headers = {"Authorization": f"Bearer {create_access_token({'sub': '8'})}"}
    async with AsyncClient(transport=ASGITransport(app=model_app), base_url="http://test") as client:
        codes = [(await client.get("/api/v1/chat/jobs/abc/events", headers=headers)).status_code for _ in range(30)]
        assert codes.count(429) == 0  # default bucket (60/min), not the 20/min model bucket
        assert (await client.post("/api/v1/chat/jobs", headers=headers)).status_code == 200
