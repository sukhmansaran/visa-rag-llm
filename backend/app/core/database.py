import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


DISPOSABLE_DATABASE_ALLOWLIST = frozenset({
    "visa_chatbot_test",
    "visa_chatbot_ci_test",
    "visa_chatbot_migration_test",
    "visa_chatbot_disposable_migration_test",
})


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> bool:
    """
    Initialize database connection and verify connectivity.
    
    Table creation via SQLModel.metadata.create_all is strictly opt-in, disabled by default
    (DATABASE_AUTO_CREATE_TABLES=False), and strictly forbidden in production, staging,
    or against unapproved databases.
    
    Schema creation is permitted only in explicitly designated test environments
    (ENVIRONMENT in {'test', 'testing', 'test_ephemeral', 'local_sandbox'})
    targeting approved disposable databases in DISPOSABLE_DATABASE_ALLOWLIST.
    
    Returns:
        bool: True if tables were created via create_all, False if creation was skipped.
    """
    if settings.DATABASE_AUTO_CREATE_TABLES:
        # 1. Environment safeguard: strictly forbid in production, staging, development
        env_lower = (settings.ENVIRONMENT or "").lower()
        allowed_envs = {"test", "testing", "test_ephemeral", "local_sandbox"}
        if env_lower not in allowed_envs:
            raise RuntimeError(
                f"CRITICAL SAFETY VIOLATION: Schema auto-creation (DATABASE_AUTO_CREATE_TABLES) "
                f"is strictly forbidden in '{settings.ENVIRONMENT}' environment. "
                f"Permitted only in: {sorted(allowed_envs)}."
            )

        # 2. Target database safeguard: strictly require database name in DISPOSABLE_DATABASE_ALLOWLIST
        from urllib.parse import urlparse
        clean_url = str(settings.DATABASE_URL).replace("+asyncpg", "")
        parsed = urlparse(clean_url)
        dbname = (parsed.path or "").lstrip("/")
        if not dbname:
            raise RuntimeError(
                "CRITICAL SAFETY VIOLATION: Cannot verify target database for schema auto-creation: "
                "database name is empty."
            )
        if dbname not in DISPOSABLE_DATABASE_ALLOWLIST:
            raise RuntimeError(
                f"CRITICAL SAFETY VIOLATION: Refusing schema auto-creation on database '{dbname}'. "
                f"Auto-creation is exclusively permitted on designated disposable databases: "
                f"{sorted(DISPOSABLE_DATABASE_ALLOWLIST)}."
            )

        logger.warning(
            f"DATABASE_AUTO_CREATE_TABLES is active in permitted environment '{settings.ENVIRONMENT}': "
            f"executing SQLModel.metadata.create_all on '{dbname}'."
        )
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        return True

    logger.info(
        "Database table auto-creation is disabled (DATABASE_AUTO_CREATE_TABLES=False). "
        "Schema is managed strictly by Alembic migrations."
    )
    # Validate database connectivity without mutating schema
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return False


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
