"""Shared pytest fixtures for the backend test suite.

Provides an async ``AsyncSession`` fixture backed by an in-memory SQLite
database (via ``aiosqlite``) for fast, isolated repository/integration tests.
Each test gets a fresh schema created from the ORM metadata and the session is
rolled back / disposed after the test so no state leaks between tests.

This deliberately avoids importing ``backend.database`` because that module
aborts at import time when ``DATABASE_URL`` is not set; tests build their own
engine instead.
"""

import os
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.models import Base

if TYPE_CHECKING:
    from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Integration test contract (tasks 7.1 / 7.2 red phase)
# ---------------------------------------------------------------------------
# The ``async_client`` fixture below assumes the following contract, which
# tasks 7.3-7.5 must implement to match:
#
#   * ``backend.main`` exposes ``create_app() -> FastAPI`` — an application
#     factory that builds the app WITHOUT triggering the DATABASE_URL check or
#     the Alembic migration lifespan at import/construction time. This lets the
#     tests build a real app instance without a running PostgreSQL database.
#   * The app resolves its ``AsyncSession`` through
#     ``backend.database.get_session`` and that dependency is overridable via
#     ``app.dependency_overrides[get_session]``.
#   * ``backend.database`` must be importable in a test environment. Today it
#     aborts at import time with ``SystemExit`` when ``DATABASE_URL`` is unset,
#     and its settings model forbids extra keys (so the project ``.env`` — which
#     carries unrelated tokens — makes import fail even when ``DATABASE_URL`` is
#     exported). The green-phase implementation (tasks 7.3-7.5) must make the
#     module importable under test, e.g. by having the settings model ignore
#     extra env keys and/or deferring the DATABASE_URL/engine check into the
#     app lifespan rather than module import. The fixture below exports a
#     throw-away ``DATABASE_URL`` to cover the first half of that requirement.
#
# The fixture overrides ``get_session`` so router -> service -> repository -> DB
# round-trips run against the same in-memory SQLite ``AsyncSession`` used by the
# rest of the backend test-suite. The overridden real engine is never used.

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


@pytest_asyncio.fixture
async def async_client(
    async_session: AsyncSession,
) -> AsyncGenerator["AsyncClient", None]:
    """Yield an ``httpx.AsyncClient`` wired to the FastAPI app over ASGI.

    Builds the app via ``backend.main.create_app()`` and overrides the
    ``get_session`` dependency so every request uses the per-test in-memory
    ``async_session`` (guaranteeing isolation and rollback between tests). The
    client talks to the app in-process through ``httpx.ASGITransport`` — no
    network socket or running server is involved.
    """
    # ``backend.database`` aborts at import time (SystemExit) when DATABASE_URL
    # is absent. The integration tests never touch a real database — the
    # ``get_session`` dependency is overridden below to use the in-memory
    # SQLite ``async_session`` — but the module must still import cleanly. Set a
    # throw-away DATABASE_URL so the import-time guard is satisfied without
    # requiring a running PostgreSQL. ``setdefault`` leaves any real value
    # (e.g. in CI) untouched.
    os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

    # Imported lazily so that collection of non-integration tests does not
    # require these modules; during the red phase these imports fail because
    # ``backend.main`` does not exist yet, which is the expected TDD state.
    from httpx import ASGITransport, AsyncClient

    from backend.database import get_session
    from backend.main import create_app

    app = create_app()

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
