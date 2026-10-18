"""Shared pytest fixtures for the backend test suite.

Provides an async ``AsyncSession`` fixture backed by an in-memory SQLite
database (via ``aiosqlite``) for fast, isolated repository/integration tests.
Each test gets a fresh schema created from the ORM metadata and the session is
rolled back / disposed after the test so no state leaks between tests.

Tests build their own in-memory engine here rather than using
``backend.database``'s lazily-initialized engine, so they never depend on
``DATABASE_URL`` or touch a real database.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import Settings, get_settings
from backend.models import Base

# In-memory SQLite via the async aiosqlite driver.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Known shared secret used by the auth guard in integration tests. The routers
# are mounted with the ``verify_api_key`` dependency (Requirements 7.2, 7.3),
# so every request must carry a matching ``X-API-Key`` header. Tests override
# ``get_settings`` with :func:`settings_override` to supply this value without
# touching the process environment, and send it via :data:`AUTH_HEADERS`.
TEST_SHARED_SECRET = "test-shared-secret"

#: Default headers that satisfy the ``verify_api_key`` guard in tests.
AUTH_HEADERS = {"X-API-Key": TEST_SHARED_SECRET}


def settings_override() -> Settings:
    """Return a :class:`Settings` carrying the known test shared secret.

    Used as a ``get_settings`` dependency override so the ``verify_api_key``
    guard accepts :data:`AUTH_HEADERS` without reading ``APP_SHARED_SECRET``
    from the environment.
    """
    return Settings(app_shared_secret=TEST_SHARED_SECRET)  # type: ignore[call-arg]


# Re-exported so tests can register the override with
# ``app.dependency_overrides[get_settings] = settings_override``.
__all__ = [
    "AUTH_HEADERS",
    "TEST_DATABASE_URL",
    "TEST_SHARED_SECRET",
    "get_settings",
    "settings_override",
]


@pytest_asyncio.fixture
async def async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh ``AsyncSession`` bound to an isolated in-memory database.

    The schema is created from ``Base.metadata`` before the test and dropped
    afterwards, guaranteeing that each test starts from an empty database.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
