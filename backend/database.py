"""Async SQLAlchemy engine and session configuration.

Reads DATABASE_URL exclusively from the process environment via
pydantic-settings (no ``.env`` fallback) and rewrites
``postgresql://`` → ``postgresql+asyncpg://`` automatically.

Initialization is *lazy*: the settings are loaded and the engine / session
factory are created on first use (the first ``get_session`` call), not at
import time. This keeps ``import backend.database`` — and therefore
``import backend.main`` — side-effect free and independent of ``DATABASE_URL``,
so the app object and the routers can be imported in any environment (including
tests that override ``get_session`` and never touch the real engine). A missing
``DATABASE_URL`` is reported the first time a real database connection is
requested, which in production happens during startup validation.
"""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class _DatabaseSettings(BaseSettings):
    """Load and validate DATABASE_URL from the environment."""

    database_url: str

    @field_validator("database_url")
    @classmethod
    def rewrite_scheme(cls, v: str) -> str:
        """Rewrite postgresql:// to postgresql+asyncpg:// for the async driver."""
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = {
        # DATABASE_URL must come exclusively from the process environment
        # (Requirement 11.1); no ``.env`` fallback is permitted, so startup
        # aborts when the variable is absent. Ignore unrelated process env vars
        # (e.g. GITHUB_TOKEN); only DATABASE_URL is consumed.
        "extra": "ignore",
    }


class DatabaseConfigError(RuntimeError):
    """Raised when ``DATABASE_URL`` is missing or invalid at first use."""


# ---------------------------------------------------------------------------
# Lazy engine / session-factory initialization
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _load_settings() -> _DatabaseSettings:
    """Load ``DATABASE_URL`` settings, raising a clear error when absent.

    Raises:
        DatabaseConfigError: When ``DATABASE_URL`` is not set (or invalid). The
            message identifies the missing variable so startup validation and
            logs point operators at the fix.
    """
    try:
        return _DatabaseSettings()  # type: ignore[call-arg]
    except Exception as exc:  # pydantic ValidationError when DATABASE_URL missing
        logger.critical(
            "DATABASE_URL environment variable is not set. "
            "The backend cannot start without a database connection. "
            "Set DATABASE_URL to a valid PostgreSQL connection string and try again."
        )
        raise DatabaseConfigError(
            "Missing required environment variable DATABASE_URL. "
            "Set it to a PostgreSQL connection string, e.g. "
            "postgresql://user:password@host:5432/dbname"
        ) from exc


def resolve_database_url() -> str:
    """Return the async-driver (``postgresql+asyncpg://``) database URL.

    This is the single, shared resolver for the connection string. It reads
    from the same source as the application engine — the process environment
    only (no ``.env`` fallback), via pydantic-settings — and applies the
    asyncpg scheme rewrite. Alembic's ``env.py`` uses this (instead of reading
    ``os.environ`` directly) so startup validation and migrations always target
    the exact same environment-only configuration.

    Raises:
        DatabaseConfigError: When ``DATABASE_URL`` cannot be resolved.
    """
    return _load_settings().database_url


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = _load_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncSession:  # type: ignore[return]
    """Yield an AsyncSession for use as a FastAPI dependency.

    Usage::

        @router.get("/")
        async def list_entries(db: AsyncSession = Depends(get_session)):
            ...
    """
    async with get_session_factory()() as session:
        yield session
