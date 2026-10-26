"""Middleware for request tracking, logging, and error handling."""
import time
import uuid
from typing import Callable
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from app.core.exceptions import AppException, app_exception_to_http_exception
from app.core.logging_config import get_logger

logger = get_logger(__name__)

import contextvars

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    """Logging filter that injects the active request_id from contextvars."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        header_id = request.headers.get("X-Request-ID")
        # Validate format (prevent arbitrary injection)
        if header_id and len(header_id) <= 64 and header_id.replace("-", "").isalnum():
            request_id = header_id
        else:
            request_id = str(uuid.uuid4())
            
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            logger.info(f"Request completed", extra={"status_code": response.status_code, "duration_ms": round(duration * 1000, 2)})
            return response
        except Exception as exc:
            logger.error(f"Request failed: {exc}", exc_info=True)
            raise

class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except AppException as exc:
            http_exc = app_exception_to_http_exception(exc)
            return JSONResponse(status_code=http_exc.status_code, content=http_exc.detail)
        except RedisError as exc:
            # Redis down (M4.7): a service is temporarily unavailable, not a server bug
            logger.error(f"Redis unavailable: {exc}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error_code": "REDIS_UNAVAILABLE",
                         "message": "A service this needs is temporarily unavailable. Please try again shortly."},
            )
        except Exception as exc:
            logger.error(f"Unexpected server error: {str(exc)}", exc_info=True)
            request_id = getattr(request.state, "request_id", None) or request_id_ctx.get()
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred. Please try again later.",
                    "request_id": request_id,
                }
            )




import hashlib
from app.core.config import settings


RATE_LIMIT_ERROR_BODY = "Rate limit exceeded ({limit} requests/min). Please slow down."

# One async Redis client per event loop, shared by all middleware instances; closed on app shutdown
from app.core.loop_local import LoopLocal

_rate_limit_redis: LoopLocal = LoopLocal()


async def close_rate_limit_redis() -> None:
    client = _rate_limit_redis.pop()
    if client is not None:
        await client.aclose()
REDIS_RETRY_SECONDS = 30
# Credential-accepting endpoints share a strict per-IP bucket
CREDENTIAL_ENDPOINTS = ("/auth/login", "/auth/signup", "/auth/refresh")
# Endpoints that start model work (seconds to minutes of CPU each): the strict per-user "llm" bucket.
# Matched by exact path suffix, so polling/reconnect routes under them (e.g. /chat/jobs/{id}/events) are not
# counted. /chat/jobs, /documents/sop/generate and /tour-packages/create were missing (2026-10-15 review).
MODEL_CALL_ENDPOINTS = (
    "/chat/answer", "/chat/answer/stream", "/chat/jobs", "/admin/diagnostic-jobs",
    "/documents/sop/generate", "/tour-packages/create", "/travel/itinerary/generate",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware (A1, N1).
    Redis-backed fixed-window counters shared across workers, with a bounded in-memory fallback.

    Per-route quotas:
      - /auth/login, /auth/signup, /auth/refresh: 10 req/min, always keyed by client IP
      - Model-call endpoints (MODEL_CALL_ENDPOINTS: chat answers and jobs, SOP, itinerary, tour packages): 20 req/min
      - Default endpoints: 60 req/min

    Identity:
      - Authenticated buckets use the user ID from a *verified* JWT; invalid/forged tokens fall back to IP.
      - X-Forwarded-For is honoured only when the direct peer is in settings.TRUSTED_PROXY_IPS.
    """
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.default_rpm = requests_per_minute
        self._redis_retry_at = 0.0
        self._memory_counts = {}
        self._max_memory_keys = 10000

    async def _get_redis(self):
        existing = _rate_limit_redis.get()
        if existing is not None:
            return existing
        if time.time() < self._redis_retry_at:
            return None
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=True,
            )
            await client.ping()
            _rate_limit_redis.set(client)
            return client
        except Exception:
            self._redis_retry_at = time.time() + REDIS_RETRY_SECONDS
            return None

    def _get_rate_limit_and_bucket(self, path: str) -> tuple[int, str]:
        path_lower = path.lower()
        if any(path_lower.endswith(p) for p in CREDENTIAL_ENDPOINTS):
            return 10, "auth"
        if path_lower.rstrip("/").endswith(MODEL_CALL_ENDPOINTS):
            return 20, "llm"
        return self.default_rpm, "default"

    @staticmethod
    def _client_ip(request: Request) -> str:
        peer_ip = request.client.host if request.client else "unknown"
        trusted = set(settings.TRUSTED_PROXY_IPS or [])
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for and peer_ip in trusted:
            # Walk right-to-left past our own proxies; the first untrusted hop is the real client
            for hop in reversed([h.strip() for h in forwarded_for.split(",") if h.strip()]):
                if hop not in trusted:
                    return hop
        return peer_ip

    @staticmethod
    def _verified_user_id(request: Request) -> str | None:
        auth_header = request.headers.get("Authorization") or ""
        if not auth_header.startswith("Bearer "):
            return None
        token = auth_header[7:].strip()
        if not token:
            return None
        try:
            import jwt
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            sub = payload.get("sub")
            return str(sub) if sub else None
        except Exception:
            return None

    def _get_client_identifier(self, request: Request, bucket: str) -> str:
        if bucket != "auth":
            user_id = self._verified_user_id(request)
            if user_id:
                return f"usr:{hashlib.sha256(user_id.encode()).hexdigest()[:16]}"
        return f"ip:{self._client_ip(request)}"

    def _too_many(self, limit: int, bucket: str) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": "RATE_LIMIT_ERROR",
                "message": RATE_LIMIT_ERROR_BODY.format(limit=limit),
                "details": {"retry_after": 60, "limit": limit, "bucket": bucket},
            },
            headers={"Retry-After": "60"},
        )

    async def _redis_count(self, rate_key: str) -> int | None:
        """Increment the Redis window counter; None if Redis is unavailable."""
        redis_client = await self._get_redis()
        if not redis_client:
            return None
        try:
            window_key = f"{rate_key}:{int(time.time() // 60)}"
            count = await redis_client.incr(window_key)
            if count == 1:
                await redis_client.expire(window_key, 60)
            return count
        except Exception:
            _rate_limit_redis.set(None)
            self._redis_retry_at = time.time() + REDIS_RETRY_SECONDS
            return None

    def _memory_count(self, rate_key: str) -> int:
        """Record a hit in the in-memory sliding window and return the count including it."""
        now = time.time()
        if rate_key not in self._memory_counts and len(self._memory_counts) >= self._max_memory_keys:
            self._memory_counts = {
                k: kept for k, v in self._memory_counts.items()
                if (kept := [ts for ts in v if now - ts < 60])
            }
            if len(self._memory_counts) >= self._max_memory_keys:
                # Still full of active keys: evict the oldest half rather than grow unbounded
                oldest = sorted(self._memory_counts, key=lambda k: self._memory_counts[k][-1])
                for k in oldest[: self._max_memory_keys // 2]:
                    del self._memory_counts[k]
        hits = [ts for ts in self._memory_counts.get(rate_key, []) if now - ts < 60]
        hits.append(now)
        self._memory_counts[rate_key] = hits
        return len(hits)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in ["/health", "/api/v1/health"]:
            return await call_next(request)

        limit, bucket = self._get_rate_limit_and_bucket(path)
        rate_key = f"rl:{bucket}:{self._get_client_identifier(request, bucket)}"

        count = await self._redis_count(rate_key)
        if count is None:
            count = self._memory_count(rate_key)
        if count > limit:
            return self._too_many(limit, bucket)

        # Downstream is called exactly once, outside any rate-limit error handling
        return await call_next(request)
