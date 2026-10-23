"""Integration tests for the summary router (``backend.routers.summary``).

Exercises the FastAPI summary router mounted on the app factory
(``backend.main``) end-to-end: ``GET /api/v1/summary/monthly`` and
``GET /api/v1/summary/annual``, including field/count correctness, the
empty-month case, and out-of-range parameter validation.

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

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings
from backend.database import get_session
from backend.main import app
from backend.models import Base, WorkEntry

from .conftest import AUTH_HEADERS, settings_override

# ``backend.database`` now initializes its engine lazily, so importing it (and
# ``backend.main``) never requires ``DATABASE_URL``. Tests override
# ``get_session`` with the in-memory SQLite session below and never touch the
# real engine.
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
        # Routers are guarded by ``verify_api_key``; supply a known secret via
        # the settings override and send the matching header on every request.
        app.dependency_overrides[get_settings] = settings_override

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
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
                (date(2025, 6, 3), "travel"),
                (date(2025, 6, 4), "vacation"),
                (date(2025, 6, 5), "sick"),
                (date(2025, 6, 6), "home"),
            ],
        )

        response = await http_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2025
        assert data["month"] == 6
        assert data["total_days"] == 5
        assert data["denmark_days"] == 1
        assert data["travel_days"] == 1
        assert data["vacation_days"] == 1
        assert data["sick_days"] == 1
        assert data["home_days"] == 1
        # 4 of 5 compliant days -> 80%
        assert data["compliance_pct"] == 80.0
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
