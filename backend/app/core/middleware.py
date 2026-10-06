"""Middleware for request tracking, logging, and error handling."""
import time
import uuid
from typing import Callable
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from app.core.exceptions import AppException, app_exception_to_http_exception
from app.core.logging_config import get_logger

logger = get_logger(__name__)

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        old_factory = logging.getLogRecordFactory()
        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.request_id = request_id
            return record
        logging.setLogRecordFactory(record_factory)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            logging.setLogRecordFactory(old_factory)

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
        print("DEBUG: ErrorHandlerMiddleware.dispatch called")
        try:
            return await call_next(request)
        except AppException as exc:
            http_exc = app_exception_to_http_exception(exc)
            return JSONResponse(status_code=http_exc.status_code, content=http_exc.detail)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Unexpected error: {str(exc)}\n{tb}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error_code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred",
                    "details": {"exception": str(exc), "traceback": tb}
                }
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in ["/health", "/api/v1/health"]:
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()
        if client_ip in self.request_counts:
            self.request_counts[client_ip] = [(ts, count) for ts, count in self.request_counts[client_ip] if current_time - ts < 60]
        if client_ip not in self.request_counts:
            self.request_counts[client_ip] = []
        recent_requests = sum(count for _, count in self.request_counts[client_ip])
        if recent_requests >= self.requests_per_minute:
            return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"error_code": "RATE_LIMIT_ERROR", "message": "Too many requests.", "details": {"retry_after": 60}})
        self.request_counts[client_ip].append((current_time, 1))
        return await call_next(request)
