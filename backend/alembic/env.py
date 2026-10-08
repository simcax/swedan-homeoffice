"""Alembic environment configuration for async SQLAlchemy (asyncpg).

Uses the same async engine as the application so migrations run against the
exact same connection settings.  The DATABASE_URL is read exclusively from the
process environment (no ``.env`` fallback) via the same pydantic-settings
mechanism used by database.py.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Set up Python logging from the ini file. ``disable_existing_loggers=False``
# preserves loggers configured before Alembic runs (e.g. ``backend.main``),
# so a migration-failure message logged by the caller is still emitted when
# migrations run in-process during application startup (Requirement 11.5).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# ---------------------------------------------------------------------------
# Import application metadata so autogenerate can detect schema changes
# ---------------------------------------------------------------------------
from backend.database import resolve_database_url
from backend.models import Base

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Resolve DATABASE_URL
# ---------------------------------------------------------------------------


def _get_url() -> str:
    """Return the async-driver database URL.

    Delegates to :func:`backend.database.resolve_database_url` — the single
    shared resolver used by the application engine — so migrations read the
    connection string from the same source as startup validation (the process
    environment only, no ``.env`` fallback) and the asyncpg scheme rewrite is
    applied once, consistently. Previously this read ``os.environ`` directly,
    which could diverge from the app's pydantic-settings resolution.
    """
    return resolve_database_url()


# ---------------------------------------------------------------------------
# Offline mode — emit SQL to stdout without connecting
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL output, no live DB required)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online (async) mode — connect and run migrations
# ---------------------------------------------------------------------------


def do_run_migrations(connection) -> None:  # type: ignore[type-arg]
    """Configure and run migrations on an existing synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine, acquire a connection, and run migrations."""
    url = _get_url()
    connectable: AsyncEngine = create_async_engine(url, echo=False)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online mode — drives the async migration coroutine."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
