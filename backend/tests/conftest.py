import sys
from pathlib import Path
import pytest
import pytest_asyncio

# Ensure backend root is on sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

import os

# The shared app is exercised by many tests from one client IP; rate limiting is covered by
# tests/test_rate_limit.py, which mounts the middleware on its own app.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from urllib.parse import urlparse

# Point the app's GLOBAL engine at the disposable test database before anything imports it.
# Several code paths (chat stream persistence, pipeline tourist lookup, crawler, workers) open
# sessions via app.core.database.AsyncSessionLocal directly rather than the get_db dependency,
# so overriding get_db alone left them writing to the real development database.
from app.core.config import settings

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    settings.DATABASE_URL.rsplit("/", 1)[0] + "/visa_chatbot_test",
)
settings.DATABASE_URL = TEST_DATABASE_URL
settings.DATABASE_USE_NULL_POOL = True  # each test runs on its own event loop

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from app.core.database import DISPOSABLE_DATABASE_ALLOWLIST, get_db
from app.core import database as app_database

assert str(app_database.engine.url).endswith(urlparse(TEST_DATABASE_URL.replace("+asyncpg", "")).path), (
    "Global engine must target the test database"
)

from app.main import app

# Safety check: Enforce that test database target is strictly disposable
_clean_test_url = TEST_DATABASE_URL.replace("+asyncpg", "")
_target_db = (urlparse(_clean_test_url).path or "").lstrip("/")
if not _target_db or _target_db not in DISPOSABLE_DATABASE_ALLOWLIST:
    raise RuntimeError(
        f"CRITICAL SAFETY VIOLATION: TEST_DATABASE_URL targets database '{_target_db}', "
        f"which is not in DISPOSABLE_DATABASE_ALLOWLIST {sorted(DISPOSABLE_DATABASE_ALLOWLIST)}!"
    )

from sqlalchemy.pool import NullPool

# Create test engine with NullPool to prevent connection lockups between tests
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)



@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh database session for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Create test client with database override."""
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()
