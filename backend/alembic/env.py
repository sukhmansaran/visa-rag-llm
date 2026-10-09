from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import asyncio
from sqlmodel import SQLModel

import sys
from pathlib import Path

# Ensure backend root is on sys.path regardless of execution CWD
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Import all models to ensure they're registered with SQLModel
import app.models

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate
target_metadata = SQLModel.metadata


def _get_target_url() -> tuple[str, bool]:
    """
    Resolve the target database URL and indicate whether an explicit override is active.
    Order of precedence:
    1. Alembic CLI -x url=... or -x db_url=...
    2. Explicit programmatic Config option 'sqlalchemy.url' (if set and not template placeholder)
    3. Environment variable ALEMBIC_DATABASE_URL
    4. Default application settings (app.core.config.settings.DATABASE_URL)
    """
    import os
    from app.core.config import settings

    x_args = context.get_x_argument(as_dictionary=True)
    cli_override = x_args.get("url") or x_args.get("db_url")
    if cli_override:
        return cli_override, True

    cfg_url = config.get_main_option("sqlalchemy.url")
    placeholder = "postgresql+asyncpg://postgres:postgres@localhost:5432/visa_chatbot"
    if cfg_url and cfg_url != placeholder and cfg_url != "driver://user:pass@localhost/dbname":
        return cfg_url, True

    env_override = os.getenv("ALEMBIC_DATABASE_URL")
    if env_override:
        return env_override, True

    # Fall back to default development database settings
    return str(settings.DATABASE_URL), False


def _safe_url_repr(url_str: str) -> str:
    """Return a sanitized URL string with passwords masked."""
    try:
        from sqlalchemy.engine import make_url
        u = make_url(url_str)
        return u.render_as_string(hide_password=True)
    except Exception:
        return "[sanitized_url]"


def _enforce_dev_safety_guard(target_url: str, is_override: bool) -> None:
    """Enforce fail-closed guard against mutating the development database."""
    import os
    from urllib.parse import urlparse

    prevent_dev = os.getenv("ALEMBIC_PREVENT_DEV_MUTATION", "").lower() in ("1", "true", "yes")
    if not prevent_dev:
        return

    if not is_override:
        raise RuntimeError(
            "ACCIDENTAL DEV TARGETING PREVENTED: ALEMBIC_PREVENT_DEV_MUTATION is active, "
            "but no explicit disposable database URL override was provided."
        )

    clean_target = target_url.replace("+asyncpg", "")
    parsed = urlparse(clean_target)
    target_dbname = (parsed.path or "").lstrip("/")
    forbidden = {"visa_chatbot", "visa_chatbot_dev"}
    if not target_dbname or target_dbname in forbidden:
        raise RuntimeError(
            f"ACCIDENTAL DEV TARGETING PREVENTED: ALEMBIC_PREVENT_DEV_MUTATION is active, "
            f"and target database '{target_dbname}' is a protected development database."
        )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    target_url, is_override = _get_target_url()
    _enforce_dev_safety_guard(target_url, is_override)

    # Offline mode requires synchronous dialect without +asyncpg
    sync_url = target_url.replace("postgresql+asyncpg://", "postgresql://")
    
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    target_url, is_override = _get_target_url()
    _enforce_dev_safety_guard(target_url, is_override)

    if is_override:
        from sqlalchemy.ext.asyncio import create_async_engine
        async_url = target_url
        if async_url.startswith("postgresql://"):
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        
        connectable = create_async_engine(async_url, poolclass=pool.NullPool)
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()
    else:
        from app.core.database import engine
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
