"""
Route Authorization Audit Test.
Verifies that all non-allowlisted endpoints require authentication
and reject unauthenticated requests with HTTP 401 Unauthorized.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

# Explicitly permitted public routes (no bearer token required)
PUBLIC_ROUTE_ALLOWLIST = {
    # System & Documentation
    ("GET", "/"),
    ("HEAD", "/"),
    ("GET", "/health"),
    ("HEAD", "/health"),
    ("GET", "/openapi.json"),
    ("HEAD", "/openapi.json"),
    ("GET", "/docs"),
    ("HEAD", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("HEAD", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
    ("HEAD", "/redoc"),

    # Health checks
    ("GET", "/api/v1/health"),
    ("HEAD", "/api/v1/health"),
    ("GET", "/api/v1/health/db"),
    ("HEAD", "/api/v1/health/db"),
    ("GET", "/api/v1/health/redis"),
    ("HEAD", "/api/v1/health/redis"),

    # Auth endpoints
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/refresh"),

    # Pricing & Webhooks
    ("GET", "/api/v1/subscription/pricing"),
    ("HEAD", "/api/v1/subscription/pricing"),
    ("POST", "/api/v1/payments/webhook"),

    # Public browse endpoints (read-only destination & cost info)
    ("GET", "/api/v1/tourist-visa/countries"),
    ("HEAD", "/api/v1/tourist-visa/countries"),
    ("GET", "/api/v1/tourist-visa/{country}"),
    ("HEAD", "/api/v1/tourist-visa/{country}"),
    ("GET", "/api/v1/travel/destinations/{country}"),
    ("HEAD", "/api/v1/travel/destinations/{country}"),
    ("GET", "/api/v1/travel/destinations/{country}/{city}"),
    ("HEAD", "/api/v1/travel/destinations/{country}/{city}"),
    ("POST", "/api/v1/travel-costs/estimate"),
    ("GET", "/api/v1/travel-costs/{country}/breakdown"),
    ("HEAD", "/api/v1/travel-costs/{country}/breakdown"),
    ("POST", "/api/v1/travel-costs/compare"),
}


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def get_all_app_routes():
    """
    Extract all (method, path) tuples the app serves.

    Newer FastAPI wraps included routers in internal objects instead of flattening them into
    app.routes, so routes are enumerated from the public OpenAPI schema plus any top-level
    routes (e.g. /docs, which are excluded from the schema).
    """
    routes = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method in HTTP_METHODS:
                routes.add((method.upper(), path))
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            for method in methods:
                routes.add((method, path))
    return sorted(routes)


@pytest.mark.asyncio
async def test_all_non_allowlisted_routes_require_authentication():
    """
    Audit all registered routes.
    Any route NOT in PUBLIC_ROUTE_ALLOWLIST must return 401 Unauthorized
    when called without an Authorization header.
    """
    all_routes = get_all_app_routes()
    assert len(all_routes) > 60, f"Sanity check: expected the full API surface, found {len(all_routes)} routes"

    unprotected_routes = []

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for method, path in all_routes:
            if (method, path) in PUBLIC_ROUTE_ALLOWLIST:
                continue

            # Fill path parameters with dummy values for request testing
            test_path = path
            for param in [
                "{user_id}", "{filename}", "{document_id}", "{watchlist_id}",
                "{notification_id}", "{review_id}", "{package_id}",
                "{app_id}", "{profile_id}", "{source_id}", "{task_id}",
                "{job_id}", "{seed_id}", "{country}", "{city}"
            ]:
                if param in test_path:
                    test_path = test_path.replace(param, "1")

            try:
                response = await client.request(method, test_path, json={})
            except Exception:
                # E.g. body validation error if payload is needed
                response = await client.request(method, test_path)

            # Route MUST reject unauthenticated access with 401 Unauthorized
            # (or 403 Forbidden in some gated middleware, but never 200 or 404/422 without auth)
            if response.status_code not in (401, 403):
                unprotected_routes.append((method, path, response.status_code))

    assert not unprotected_routes, (
        f"Found {len(unprotected_routes)} route(s) lacking required authentication: "
        f"{unprotected_routes}"
    )
