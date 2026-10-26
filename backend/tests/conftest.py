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
# The monitor model (M4.5) adds a model call to verified and uncertain messages; tests that script the model would all
# need a reply for it. Off by default here; tests/test_monitor.py switches it on.
os.environ.setdefault("MONITOR_ENABLED", "false")

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
# Tests use a separate Redis logical database so revoked-token / rate-limit keys never land in the app's db 0
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", settings.REDIS_URL.rsplit("/", 1)[0] + "/15")
settings.REDIS_URL = TEST_REDIS_URL
# ...and a throwaway Chroma store (M0.14): ingestion now deletes superseded chunks by source id, and test source
# ids (1, 2, ...) overlap real ones, so tests must never open the real knowledge base in ./chroma_data
import tempfile  # noqa: E402

settings.CHROMA_PERSIST_DIRECTORY = tempfile.mkdtemp(prefix="pendu_test_chroma_")

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


def _drop_tables_without_models(sync_conn) -> None:
    """
    Drop tables in the test database that no model defines any more (e.g. the versioning tables removed in
    M0.14b). drop_all only knows current models, so a leftover table with a foreign key into `documents` made
    every test's reset fail. Test database only: its name was checked against the disposable allowlist above.
    """
    from sqlalchemy import inspect, text

    for table in set(inspect(sync_conn).get_table_names()) - set(SQLModel.metadata.tables) - {"alembic_version"}:
        sync_conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh database session for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(_drop_tables_without_models)
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


@pytest.fixture
def fake_llm(monkeypatch):
    """Route every model call through a scripted FakeLLM (no Ollama needed). See app/services/llm_fake.py."""
    from app.services.llm import llm_service
    from app.services.llm_fake import FakeLLM

    fake = FakeLLM()
    for name in ("generate_answer", "generate_answer_stream", "structured_call"):
        monkeypatch.setattr(llm_service, name, getattr(fake, name))
    return fake
