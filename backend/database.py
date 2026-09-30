"""Async SQLAlchemy engine and session configuration.

Reads ``DATABASE_URL`` from the environment via pydantic-settings and rewrites
``postgresql://`` → ``postgresql+asyncpg://`` automatically for the async
driver.

Importing this module is side-effect free: it does NOT create an engine or
require ``DATABASE_URL`` at import time. The engine and session factory are
built lazily on first use (see :func:`get_session`), and the presence of
``DATABASE_URL`` is enforced by the application lifespan in
:mod:`backend.main` rather than here. This keeps the module importable in test
environments where no real database is configured — tests override the
``get_session`` dependency to use an in-memory SQLite session instead.
"""

import logging

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class _DatabaseSettings(BaseSettings):
    """Load and validate ``DATABASE_URL`` from the environment.

    Extra environment keys (e.g. unrelated deployment tokens carried in the
    project ``.env``) are ignored rather than rejected, so importing this
    module never fails on unrelated configuration.
    """

    database_url: str

    @field_validator("database_url")
    @classmethod
    def rewrite_scheme(cls, v: str) -> str:
        """Rewrite ``postgresql://`` to ``postgresql+asyncpg://``."""
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# ---------------------------------------------------------------------------
# Lazy engine / session factory
# ---------------------------------------------------------------------------
#
# These are created on first use rather than at import time so that merely
# importing ``backend.database`` (and calling ``create_app()`` in tests) never
# requires ``DATABASE_URL`` or opens a connection pool.

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_settings() -> _DatabaseSettings:
    """Return validated database settings, reading ``DATABASE_URL`` from env.

    Raises:
        pydantic.ValidationError: if ``DATABASE_URL`` is not set.
    """
    return _DatabaseSettings()  # type: ignore[call-arg]


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
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
    """Yield an ``AsyncSession`` for use as a FastAPI dependency.

    Tests override this dependency by identity
    (``app.dependency_overrides[get_session]``) to substitute an in-memory
    SQLite session, so routers must depend on this exact symbol.

    Usage::

        @router.get("/")
        async def list_entries(db: AsyncSession = Depends(get_session)):
            ...
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
