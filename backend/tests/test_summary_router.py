"""Failing integration tests for the summary router (TDD red phase — task 7.2).

These tests exercise the full router -> service -> repository -> DB round-trip
for the yet-to-be-implemented summary router. They are expected to FAIL at
import/collection time because ``backend.main`` and ``backend.routers.summary``
do not exist yet; they are implemented in tasks 7.4 and 7.5.

Assumed contract (implement tasks 7.4-7.5 to match)
---------------------------------------------------
* ``backend.main`` exposes a ``create_app() -> FastAPI`` application factory
  that builds the app *without* triggering the DATABASE_URL check / Alembic
  migration lifespan side-effects at import time, and registers the summary
  router (prefix ``/api/v1/summary``).
* The app depends on ``backend.database.get_session`` for its ``AsyncSession``.
  Tests override it via ``app.dependency_overrides[get_session]`` so requests
  run against the in-memory SQLite ``AsyncSession`` from ``conftest.py``. The
  shared ``async_client`` fixture lives in ``conftest.py`` and is reused here.

Endpoints under test (from the design document)::

    GET /api/v1/summary/monthly?year=&month=   -> 200 ComplianceSummary
    GET /api/v1/summary/annual?year=           -> 200 AnnualSummary

Validation rules exercised here:
* ``year`` outside 2000-2099 or ``month`` outside 1-12 -> 422

Requirements: 6.1, 6.2, 6.3, 6.5, 7.1, 7.2, 7.5, 7.6
"""

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# GET /api/v1/summary/monthly
# ---------------------------------------------------------------------------


class TestMonthlySummary:
    async def test_returns_all_required_fields_with_correct_counts(
        self, async_client: AsyncClient
    ) -> None:
        # 2 denmark, 1 vacation, 1 sick, 1 home -> 4 compliant / 5 total = 80%.
        seed = [
            ("2025-06-02", "denmark"),
            ("2025-06-03", "denmark"),
            ("2025-06-04", "vacation"),
            ("2025-06-05", "sick"),
            ("2025-06-06", "home"),
        ]
        for work_date, location in seed:
            created = await async_client.post(
                "/api/v1/entries",
                json={"work_date": work_date, "location": location},
            )
            assert created.status_code == 201

        response = await async_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2025
        assert data["month"] == 6
        assert data["total_days"] == 5
        assert data["denmark_days"] == 2
        assert data["vacation_days"] == 1
        assert data["sick_days"] == 1
        assert data["home_days"] == 1
        assert data["compliance_pct"] == 80.0
        assert data["is_compliant"] is True

    async def test_no_entries_returns_zero_and_not_compliant(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_days"] == 0
        assert data["compliance_pct"] == 0.0
        assert data["is_compliant"] is False

    async def test_month_out_of_range_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get(
            "/api/v1/summary/monthly", params={"year": 2025, "month": 13}
        )
        assert response.status_code == 422

    async def test_year_out_of_range_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get(
            "/api/v1/summary/monthly", params={"year": 1999, "month": 6}
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/summary/annual
# ---------------------------------------------------------------------------


class TestAnnualSummary:
    async def test_returns_monthly_breakdown_with_exactly_12_items(
        self, async_client: AsyncClient
    ) -> None:
        for work_date, location in [
            ("2025-01-10", "denmark"),
            ("2025-06-15", "home"),
            ("2025-12-31", "sick"),
        ]:
            created = await async_client.post(
                "/api/v1/entries",
                json={"work_date": work_date, "location": location},
            )
            assert created.status_code == 201

        response = await async_client.get(
            "/api/v1/summary/annual", params={"year": 2025}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["year"] == 2025
        assert len(data["monthly_breakdown"]) == 12
        months = [item["month"] for item in data["monthly_breakdown"]]
        assert months == list(range(1, 13))

    async def test_invalid_year_returns_422(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            "/api/v1/summary/annual", params={"year": 1999}
        )
        assert response.status_code == 422
