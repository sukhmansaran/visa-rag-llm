from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import asyncio
from sqlmodel import SQLModel

# Import all models to ensure they're registered with SQLModel
from app.models.user import User
from app.models.profile import Profile
from app.models.source import Source
from app.models.document import Document
from app.models.vector_chunk import VectorChunk
from app.models.watchlist import Watchlist
from app.models.notification import Notification
from app.models.user_document import UserDocument
from app.models.review import Review
from app.models.chat_message import ChatMessage
from app.models.change import Change  # NEW

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for autogenerate
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
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
    from app.core.database import engine
    
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
