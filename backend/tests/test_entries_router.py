"""Failing integration tests for the entries router (TDD red phase — task 7.1).

These tests exercise the full router -> service -> repository -> DB round-trip
for the yet-to-be-implemented entries router. They are expected to FAIL at
import/collection time because ``backend.main`` and ``backend.routers.entries``
do not exist yet; they are implemented in tasks 7.3 and 7.5.

Assumed contract (implement tasks 7.3-7.5 to match)
---------------------------------------------------
* ``backend.main`` exposes a ``create_app() -> FastAPI`` application factory
  that builds the app *without* triggering the DATABASE_URL check / Alembic
  migration lifespan side-effects at import time. The factory must register the
  entries router (prefix ``/api/v1/entries``) and the summary router.
* The app depends on ``backend.database.get_session`` for its ``AsyncSession``.
  Tests override it via ``app.dependency_overrides[get_session]`` so requests
  run against the in-memory SQLite ``AsyncSession`` from ``conftest.py`` instead
  of a real PostgreSQL database.

Endpoints under test (from the design document)::

    GET    /api/v1/entries?year=&month=   -> 200 list[WorkEntryResponse]
    POST   /api/v1/entries                -> 201 WorkEntryResponse
    PATCH  /api/v1/entries/{entry_id}     -> 200 WorkEntryResponse
    DELETE /api/v1/entries/{entry_id}     -> 204

Validation rules exercised here:
* future ``work_date`` -> 422
* unknown ``location`` -> 422
* ``month`` < 1 or > 12, or ``year`` < 2000 -> 422
* PATCH / DELETE of a nonexistent id -> 404

Requirements: 1.1, 1.2, 1.6, 2.1, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4
"""

from datetime import date, timedelta

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# POST /api/v1/entries
# ---------------------------------------------------------------------------


class TestCreateEntry:
    async def test_valid_body_returns_201_and_correct_json(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.post(
            "/api/v1/entries",
            json={"work_date": "2025-06-10", "location": "denmark"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["work_date"] == "2025-06-10"
        assert data["location"] == "denmark"
        assert "id" in data

    async def test_future_date_returns_422(self, async_client: AsyncClient) -> None:
        future = (date.today() + timedelta(days=1)).isoformat()  # noqa: DTZ011

        response = await async_client.post(
            "/api/v1/entries",
            json={"work_date": future, "location": "denmark"},
        )

        assert response.status_code == 422

    async def test_invalid_location_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.post(
            "/api/v1/entries",
            json={"work_date": "2025-06-10", "location": "moon"},
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/entries?year=&month=
# ---------------------------------------------------------------------------


class TestListEntries:
    async def test_returns_list_ordered_by_date(
        self, async_client: AsyncClient
    ) -> None:
        # Insert out of chronological order.
        for work_date, location in [
            ("2025-06-20", "home"),
            ("2025-06-05", "denmark"),
            ("2025-06-12", "vacation"),
        ]:
            create = await async_client.post(
                "/api/v1/entries",
                json={"work_date": work_date, "location": location},
            )
            assert create.status_code == 201

        response = await async_client.get(
            "/api/v1/entries", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        work_dates = [item["work_date"] for item in response.json()]
        assert work_dates == ["2025-06-05", "2025-06-12", "2025-06-20"]

    async def test_returns_empty_list_when_no_entries(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get(
            "/api/v1/entries", params={"year": 2025, "month": 6}
        )

        assert response.status_code == 200
        assert response.json() == []

    async def test_month_below_one_returns_422(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            "/api/v1/entries", params={"year": 2025, "month": 0}
        )
        assert response.status_code == 422

    async def test_month_above_twelve_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.get(
            "/api/v1/entries", params={"year": 2025, "month": 13}
        )
        assert response.status_code == 422

    async def test_year_below_2000_returns_422(self, async_client: AsyncClient) -> None:
        response = await async_client.get(
            "/api/v1/entries", params={"year": 1999, "month": 6}
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/v1/entries/{entry_id}
# ---------------------------------------------------------------------------


class TestUpdateEntry:
    async def test_valid_body_returns_200_updated_location_date_unchanged(
        self, async_client: AsyncClient
    ) -> None:
        created = await async_client.post(
            "/api/v1/entries",
            json={"work_date": "2025-06-10", "location": "home"},
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        response = await async_client.patch(
            f"/api/v1/entries/{entry_id}",
            json={"location": "denmark"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == entry_id
        assert data["location"] == "denmark"
        assert data["work_date"] == "2025-06-10"

    async def test_nonexistent_id_returns_404(self, async_client: AsyncClient) -> None:
        response = await async_client.patch(
            "/api/v1/entries/999999",
            json={"location": "denmark"},
        )

        assert response.status_code == 404

    async def test_invalid_location_returns_422(
        self, async_client: AsyncClient
    ) -> None:
        created = await async_client.post(
            "/api/v1/entries",
            json={"work_date": "2025-06-10", "location": "home"},
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        response = await async_client.patch(
            f"/api/v1/entries/{entry_id}",
            json={"location": "moon"},
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/entries/{entry_id}
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    async def test_existing_entry_returns_204(self, async_client: AsyncClient) -> None:
        created = await async_client.post(
            "/api/v1/entries",
            json={"work_date": "2025-06-10", "location": "denmark"},
        )
        assert created.status_code == 201
        entry_id = created.json()["id"]

        response = await async_client.delete(f"/api/v1/entries/{entry_id}")

        assert response.status_code == 204

        # The entry should no longer be listed for its month.
        listing = await async_client.get(
            "/api/v1/entries", params={"year": 2025, "month": 6}
        )
        assert listing.json() == []

    async def test_nonexistent_entry_returns_404(
        self, async_client: AsyncClient
    ) -> None:
        response = await async_client.delete("/api/v1/entries/999999")

        assert response.status_code == 404
