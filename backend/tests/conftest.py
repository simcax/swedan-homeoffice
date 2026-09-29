"""Shared pytest fixtures for the backend test suite.

Provides an async ``AsyncSession`` fixture backed by an in-memory SQLite
database (via ``aiosqlite``) for fast, isolated repository/integration tests.
Each test gets a fresh schema created from the ORM metadata and the session is
rolled back / disposed after the test so no state leaks between tests.

This deliberately avoids importing ``backend.database`` because that module
aborts at import time when ``DATABASE_URL`` is not set; tests build their own
engine instead.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models import Base

# In-memory SQLite via the async aiosqlite driver.
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


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
