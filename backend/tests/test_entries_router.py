"""Integration tests for the entries router (``backend.routers.entries``).

Exercises the entries CRUD router mounted on the FastAPI app factory
(``backend.main``) end-to-end: create/list/update/delete at
``/api/v1/entries``, plus validation (future dates, unknown locations,
out-of-range query params) and not-found handling.

Testing approach
----------------
* The app is created via ``backend.main.create_app()`` (app factory pattern).
* ``backend.database.get_session`` is overridden with a dependency that yields
  the shared in-memory-SQLite ``async_session`` fixture from ``conftest.py`` so
  every request in a test observes the same isolated database. The schema is
  created/dropped per test by that fixture, giving per-test rollback semantics.
* Requests are issued with ``httpx.AsyncClient`` over ``ASGITransport`` against
  the ASGI app (no network, no running server).

Endpoint contract under test (from the design document)::

    GET    /api/v1/entries?year=YYYY&month=MM  -> 200 list[WorkEntryResponse]
    POST   /api/v1/entries                     -> 201 WorkEntryResponse
    PATCH  /api/v1/entries/{entry_id}          -> 200 WorkEntryResponse
    DELETE /api/v1/entries/{entry_id}          -> 204

Requirements: 1.1, 1.2, 1.6, 2.1, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4
"""

import os
from collections.abc import AsyncGenerator
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ``backend.database`` (imported transitively by ``backend.main`` and the
# entries router) aborts at import time when ``DATABASE_URL`` is missing. Tests
# never touch the real engine — the ``get_session`` dependency is overridden to
# use the in-memory-SQLite ``async_session`` fixture — so a throwaway value is
# injected here purely to satisfy the import-time guard.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

API = "/api/v1/entries"


@pytest_asyncio.fixture
async def client(async_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an ``AsyncClient`` bound to the app with a per-test DB session.

    The ``get_session`` dependency is overridden to yield the shared
    in-memory-SQLite session created by the ``async_session`` fixture, so the
    router and the test observe the same rolled-back-per-test database.

    A fresh app is built per test via ``create_app()`` (migrations disabled by
    default) so dependency overrides never leak between tests.
    """
    from backend.database import get_session
    from backend.main import create_app

    app = create_app()

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/entries
# ---------------------------------------------------------------------------


class TestCreateEntry:
    async def test_valid_body_returns_201_and_correct_json(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            API, json={"work_date": "2025-06-10", "location": "denmark"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["work_date"] == "2025-06-10"
        assert data["location"] == "denmark"
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_future_date_returns_422(self, client: AsyncClient) -> None:
        future = (date.today() + timedelta(days=1)).isoformat()  # noqa: DTZ011

        response = await client.post(
            API, json={"work_date": future, "location": "denmark"}
        )

        assert response.status_code == 422

    async def test_invalid_location_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            API, json={"work_date": "2025-06-10", "location": "office"}
        )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/entries?year=&month=
# ---------------------------------------------------------------------------


class TestListEntries:
    async def test_returns_list_ordered_by_date(self, client: AsyncClient) -> None:
        # Insert out of order via the API.
        await client.post(API, json={"work_date": "2025-06-20", "location": "home"})
        await client.post(API, json={"work_date": "2025-06-05", "location": "denmark"})
        await client.post(API, json={"work_date": "2025-06-12", "location": "vacation"})

        response = await client.get(API, params={"year": 2025, "month": 6})

        assert response.status_code == 200
        data = response.json()
        work_dates = [entry["work_date"] for entry in data]
        assert work_dates == ["2025-06-05", "2025-06-12", "2025-06-20"]

    async def test_returns_empty_list_when_none_exist(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(API, params={"year": 2025, "month": 6})

        assert response.status_code == 200
        assert response.json() == []

    async def test_month_below_1_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(API, params={"year": 2025, "month": 0})
        assert response.status_code == 422

    async def test_month_above_12_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(API, params={"year": 2025, "month": 13})
        assert response.status_code == 422

    async def test_year_below_2000_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(API, params={"year": 1999, "month": 6})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/v1/entries/{entry_id}
# ---------------------------------------------------------------------------


class TestUpdateEntry:
    async def test_valid_body_returns_200_and_updated_location(
        self, client: AsyncClient
    ) -> None:
        created = await client.post(
            API, json={"work_date": "2025-06-10", "location": "home"}
        )
        entry_id = created.json()["id"]

        response = await client.patch(f"{API}/{entry_id}", json={"location": "denmark"})

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == entry_id
        assert data["location"] == "denmark"
        # work_date is unchanged by a PATCH.
        assert data["work_date"] == "2025-06-10"

    async def test_nonexistent_id_returns_404(self, client: AsyncClient) -> None:
        response = await client.patch(f"{API}/999999", json={"location": "denmark"})

        assert response.status_code == 404

    async def test_invalid_location_returns_422(self, client: AsyncClient) -> None:
        created = await client.post(
            API, json={"work_date": "2025-06-10", "location": "home"}
        )
        entry_id = created.json()["id"]

        response = await client.patch(f"{API}/{entry_id}", json={"location": "office"})

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/entries/{entry_id}
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    async def test_existing_entry_returns_204(self, client: AsyncClient) -> None:
        created = await client.post(
            API, json={"work_date": "2025-06-10", "location": "denmark"}
        )
        entry_id = created.json()["id"]

        response = await client.delete(f"{API}/{entry_id}")

        assert response.status_code == 204

    async def test_delete_removes_entry(self, client: AsyncClient) -> None:
        created = await client.post(
            API, json={"work_date": "2025-06-10", "location": "denmark"}
        )
        entry_id = created.json()["id"]

        await client.delete(f"{API}/{entry_id}")

        listed = await client.get(API, params={"year": 2025, "month": 6})
        assert listed.json() == []

    async def test_nonexistent_entry_returns_404(self, client: AsyncClient) -> None:
        response = await client.delete(f"{API}/999999")

        assert response.status_code == 404


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
