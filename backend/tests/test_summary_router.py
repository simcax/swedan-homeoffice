"""Failing integration tests for the summary router (TDD red phase — task 7.2).

These tests describe the behaviour of the yet-to-be-implemented FastAPI
summary router (``backend.routers.summary``) mounted on the app factory
(``backend.main``). They are expected to FAIL at import time (neither module
exists yet) until tasks 7.4 and 7.5 implement them.

The router interface under test (from the design document)::

    router = APIRouter(prefix="/api/v1/summary", tags=["summary"])

    @router.get("/monthly", response_model=ComplianceSummaryResponse)
    async def monthly_summary(year: int, month: int, db: AsyncSession): ...

    @router.get("/annual", response_model=AnnualSummaryResponse)
    async def annual_summary(year: int, db: AsyncSession): ...

Tests drive the app through ``httpx.AsyncClient`` + ``ASGITransport`` and
override the ``get_session`` dependency with a per-test in-memory
``AsyncSession`` that is rolled back / disposed after each test (matching the
fixture conventions in ``conftest.py``).

Requirements: 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.5, 7.6
"""

from collections.abc import AsyncGenerator
from datetime import date
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

from backend.database import get_session
from backend.main import app
from backend.models import Base, WorkEntry

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[tuple[AsyncClient, AsyncSession], None]:
    """Yield an ``AsyncClient`` bound to the app plus its backing session.

    A fresh in-memory SQLite database is created from ``Base.metadata`` for
    each test. The app's ``get_session`` dependency is overridden to hand out
    the same session so data seeded via the returned session is visible to the
    HTTP handlers. Everything is rolled back / disposed after the test.
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

        async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
            yield session

        app.dependency_overrides[get_session] = _override_get_session

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as http_client:
            try:
                yield http_client, session
            finally:
                app.dependency_overrides.clear()
                await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


async def _seed(session: AsyncSession, entries: list[tuple[date, str]]) -> None:
    """Insert ``(work_date, location)`` rows and commit them."""
    for work_date, location in entries:
        session.add(WorkEntry(work_date=work_date, location=location))
    await session.commit()


# ---------------------------------------------------------------------------
# GET /api/v1/summary/monthly
# ---------------------------------------------------------------------------


class TestMonthlySummary:
    async def test_returns_all_required_fields_with_correct_counts(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, session = client
        await _seed(
            session,
            [
                (date(2025, 6, 2), "denmark"),
                (date(2025, 6, 3), "vacation"),
                (date(2025, 6, 4), "sick"),
                (date(2025, 6, 5), "home"),
            ],
        )

        response = await http_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2025
        assert data["month"] == 6
        assert data["total_days"] == 4
        assert data["denmark_days"] == 1
        assert data["vacation_days"] == 1
        assert data["sick_days"] == 1
        assert data["home_days"] == 1
        # 3 of 4 compliant days -> 75%
        assert data["compliance_pct"] == 75.0
        assert data["is_compliant"] is True

    async def test_no_entries_returns_zeroed_non_compliant_summary(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, _session = client

        response = await http_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_days"] == 0
        assert data["compliance_pct"] == 0.0
        assert data["is_compliant"] is False

    async def test_out_of_range_month_returns_422(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, _session = client

        response = await http_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 13}
        )

        assert response.status_code == 422

    async def test_out_of_range_year_returns_422(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, _session = client

        response = await http_client.get(
            "/api/v1/summary/monthly", params={"year": 1999, "month": 6}
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/summary/annual
# ---------------------------------------------------------------------------


class TestAnnualSummary:
    async def test_returns_monthly_breakdown_with_exactly_twelve_items(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, session = client
        await _seed(
            session,
            [
                (date(2025, 1, 10), "denmark"),
                (date(2025, 6, 15), "home"),
                (date(2025, 12, 31), "vacation"),
            ],
        )

        response = await http_client.get(
            "/api/v1/summary/annual", params={"year": 2025}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2025
        assert len(data["monthly_breakdown"]) == 12
        months = [s["month"] for s in data["monthly_breakdown"]]
        assert months == list(range(1, 13))

    async def test_invalid_year_returns_422(
        self, client: tuple[AsyncClient, AsyncSession]
    ) -> None:
        http_client, _session = client

        response = await http_client.get(
            "/api/v1/summary/annual", params={"year": 3000}
        )

        assert response.status_code == 422


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
