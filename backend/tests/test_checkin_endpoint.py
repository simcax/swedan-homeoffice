"""Example, integration, and smoke tests for the check-in endpoint (task 7).

These tests cover the *non-property* wiring of the authenticated
``POST /api/v1/checkin`` endpoint (``backend.routers.checkin``): endpoint
existence and the no-body contract, authentication, the upsert-only write
assertion, 409 conflict handling, 503 database-availability handling, and the
explicit non-real-date / Local_Date boundary examples. Property-based coverage
of the write path lives in ``test_checkin_properties.py``.

Testing approach
----------------
* The app is built via ``backend.main.create_app()`` (app factory pattern),
  mirroring ``test_entries_router.py`` and ``test_db_errors.py``.
* ``backend.database.get_session`` is overridden to yield the shared in-memory
  SQLite ``async_session`` fixture from ``conftest.py`` so each request observes
  the same isolated, rolled-back-per-test database.
* ``backend.config.get_settings`` is overridden with ``settings_override`` so
  the ``verify_api_key`` guard accepts the known ``AUTH_HEADERS`` secret.
* Requests go through ``httpx.AsyncClient`` over ``ASGITransport`` — no network,
  no running server.

Requirements: 1.1, 1.7, 3.1, 3.2, 3.3, 3.4, 5.2, 5.4, 7.1, 7.3, 8.1, 8.2, 8.3,
8.4
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_session
from backend.main import create_app
from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkLocation
from backend.services import entry_service
from backend.services.checkin_resolver import local_date

from .conftest import AUTH_HEADERS, TEST_SHARED_SECRET, settings_override

CHECKIN_API = "/api/v1/checkin"


@pytest_asyncio.fixture
async def client(async_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Yield an ``AsyncClient`` bound to the app with a per-test DB session.

    The ``get_session`` dependency yields the shared in-memory-SQLite session
    from the ``async_session`` fixture and ``get_settings`` is overridden so the
    ``verify_api_key`` guard accepts :data:`AUTH_HEADERS`. A fresh app is built
    per test so dependency overrides never leak between tests.
    """
    app = create_app()

    async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_settings] = settings_override

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def _count_rows(session: AsyncSession) -> int:
    """Return the total number of ``WorkEntry`` rows persisted."""
    result = await session.execute(select(func.count()).select_from(WorkEntry))
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Task 7.1 - Endpoint existence and no-body contract (Requirements 1.1, 1.7)
# ---------------------------------------------------------------------------


class TestEndpointExistsAndNoBody:
    """The route exists, accepts POST, and ignores any request body."""

    async def test_route_exists_and_accepts_post(self, client: AsyncClient) -> None:
        # A bare POST with a valid key must reach the handler and succeed
        # (not 404/405), confirming the POST route is mounted (Requirement 1.1).
        response = await client.post(CHECKIN_API)

        assert response.status_code not in (404, 405)
        assert response.status_code == 201

    async def test_get_method_not_allowed(self, client: AsyncClient) -> None:
        # Only POST is exposed; GET on the same path must be 405, proving the
        # endpoint is method-scoped to POST (Requirement 1.1).
        response = await client.get(CHECKIN_API)

        assert response.status_code == 405

    async def test_no_body_and_arbitrary_body_succeed_identically(
        self, client: AsyncClient, async_session: AsyncSession
    ) -> None:
        # Requirement 1.7: no JSON body is required and any body present is
        # ignored. A request with no body and a request with an arbitrary JSON
        # body must produce the same persisted result for the same date.
        no_body = await client.post(CHECKIN_API)
        assert no_body.status_code == 201
        first = no_body.json()

        # An arbitrary JSON body for the same (default) date is ignored; the
        # existing row is simply upserted, yielding a 200 with identical data.
        arbitrary_body = await client.post(
            CHECKIN_API,
            json={"anything": "ignored", "location": "sick", "nested": {"x": 1}},
        )
        assert arbitrary_body.status_code == 200
        second = arbitrary_body.json()

        # Same identity, same resolved values: the body never influenced either
        # request (default denmark on the Local_Date both times).
        assert second["id"] == first["id"]
        assert second["work_date"] == first["work_date"]
        assert second["location"] == first["location"] == WorkLocation.DENMARK.value

        # Only one row persisted for the Local_Date despite two requests.
        assert await _count_rows(async_session) == 1


# ---------------------------------------------------------------------------
# Task 7.2 - Authentication (Requirements 3.1, 3.2, 3.3, 3.4)
# ---------------------------------------------------------------------------


class TestAuthentication:
    """The endpoint is guarded by the shared-secret ``verify_api_key``."""

    async def test_valid_key_reaches_handler(
        self, client: AsyncClient, async_session: AsyncSession
    ) -> None:
        # Requirement 3.1: a byte-for-byte matching X-API-Key reaches the
        # handler and the check-in succeeds.
        response = await client.post(
            CHECKIN_API, headers={"X-API-Key": TEST_SHARED_SECRET}
        )

        assert response.status_code == 201
        assert await _count_rows(async_session) == 1

    async def test_missing_key_returns_401_and_no_write(
        self, async_session: AsyncSession
    ) -> None:
        # Requirement 3.2: omitting the header rejects with 401 and no entry is
        # created. The shared ``client`` fixture injects AUTH_HEADERS by
        # default, so build a dedicated client with *no* default headers to
        # exercise the genuinely-missing-header path.
        app = create_app()

        async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
            yield async_session

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_settings] = settings_override

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as no_auth:
            response = await no_auth.post(CHECKIN_API)

        app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}
        assert await _count_rows(async_session) == 0

    async def test_wrong_key_returns_401_and_no_write(
        self, client: AsyncClient, async_session: AsyncSession
    ) -> None:
        # Requirement 3.3: a non-matching key rejects with 401 and no write.
        response = await client.post(
            CHECKIN_API, headers={"X-API-Key": "definitely-wrong"}
        )

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}
        assert await _count_rows(async_session) == 0

    async def test_empty_string_key_returns_401_and_no_write(
        self, client: AsyncClient, async_session: AsyncSession
    ) -> None:
        # Requirement 3.4 (explicit edge case): an empty-string key rejects with
        # 401 and no write occurs.
        response = await client.post(CHECKIN_API, headers={"X-API-Key": ""})

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}
        assert await _count_rows(async_session) == 0


# ---------------------------------------------------------------------------
# Task 7.3 - Upsert-only write assertion (Requirement 7.1)
# ---------------------------------------------------------------------------


class TestUpsertOnlyWritePath:
    """The handler performs writes exclusively through ``EntryService.upsert_entry``."""

    async def test_handler_writes_only_through_upsert_entry(
        self,
        client: AsyncClient,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Requirement 7.1: wrap EntryService.upsert_entry with a spy and assert
        # it is the only write path invoked. The spy delegates to the real
        # implementation so the row is genuinely persisted (no mocking of DB).
        calls: list[tuple[object, object]] = []
        real_upsert = entry_service.EntryService.upsert_entry

        async def _spy_upsert(self, work_date, location):  # type: ignore[no-untyped-def]
            calls.append((work_date, location))
            return await real_upsert(self, work_date, location)

        monkeypatch.setattr(entry_service.EntryService, "upsert_entry", _spy_upsert)

        response = await client.post(
            CHECKIN_API, params={"location": "home", "date": local_date().isoformat()}
        )

        assert response.status_code == 201
        # The single write went through upsert_entry exactly once, with the
        # resolved (date, location).
        assert len(calls) == 1
        assert calls[0][0] == local_date()
        assert calls[0][1] == WorkLocation.HOME

        # And exactly one row was persisted as a result of that upsert.
        assert await _count_rows(async_session) == 1

    async def test_special_day_short_circuit_issues_no_write(
        self,
        client: AsyncClient,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Special-day protection returns the stored entry unchanged and must not
        # invoke the write path at all (upsert_entry is never called).
        work_date = local_date()

        # Seed a vacation (special) day for the target date through the service.
        service = entry_service.EntryService(EntryRepository(async_session))
        await service.upsert_entry(work_date, WorkLocation.VACATION)

        calls: list[tuple[object, object]] = []
        real_upsert = entry_service.EntryService.upsert_entry

        async def _spy_upsert(self, wd, loc):  # type: ignore[no-untyped-def]
            calls.append((wd, loc))
            return await real_upsert(self, wd, loc)

        monkeypatch.setattr(entry_service.EntryService, "upsert_entry", _spy_upsert)

        response = await client.post(
            CHECKIN_API, params={"location": "denmark", "date": work_date.isoformat()}
        )

        assert response.status_code == 200
        assert response.json()["location"] == WorkLocation.VACATION.value
        # No write path invoked for the protected special day.
        assert calls == []
        assert await _count_rows(async_session) == 1


# ---------------------------------------------------------------------------
# Task 7.4 - 409 conflict integration (Requirement 7.3)
# ---------------------------------------------------------------------------


class TestConflictReturns409:
    """A concurrent insert violating the unique constraint surfaces as 409.

    Mirrors the entries-router conflict handling: force the create path (so
    ``upsert_entry`` inserts), make the insert's ``commit`` raise
    ``IntegrityError`` as the ``work_date`` unique constraint would, and assert
    the handler rolls back and returns 409 with no duplicate row.
    """

    async def test_integrity_error_returns_409_and_rolls_back(
        self,
        client: AsyncClient,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the create path: pretend no row exists so upsert_entry inserts.
        async def _always_missing(self: EntryRepository, work_date: object) -> None:
            return None

        monkeypatch.setattr(EntryRepository, "get_by_date", _always_missing)

        # Make the insert's commit collide with the unique constraint, and
        # record that the router rolls the session back afterwards.
        rolled_back = {"called": False}

        async def _raise_integrity_error() -> None:
            raise IntegrityError("INSERT ...", params=None, orig=Exception("duplicate"))

        real_rollback = async_session.rollback

        async def _tracking_rollback() -> None:
            rolled_back["called"] = True
            await real_rollback()

        monkeypatch.setattr(async_session, "commit", _raise_integrity_error)
        monkeypatch.setattr(async_session, "rollback", _tracking_rollback)

        response = await client.post(
            CHECKIN_API,
            params={"location": "denmark", "date": local_date().isoformat()},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == "Entry already exists for this date"
        assert rolled_back["called"], "the session was not rolled back"

    async def test_conflict_leaves_existing_entry_unchanged_and_no_duplicate(
        self,
        async_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seed a real pre-existing entry for the target date.
        work_date = local_date()
        service = entry_service.EntryService(EntryRepository(async_session))
        seeded = await service.upsert_entry(work_date, WorkLocation.HOME)
        seeded_id = seeded.id
        seeded_location = seeded.location

        # Build a client whose handler is forced down the *create* path for the
        # already-occupied date, so the insert collides with the unique
        # constraint and raises IntegrityError on commit.
        app = create_app()

        async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
            yield async_session

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_settings] = settings_override

        async def _always_missing(self: EntryRepository, wd: object) -> None:
            return None

        monkeypatch.setattr(EntryRepository, "get_by_date", _always_missing)

        async def _raise_integrity_error() -> None:
            raise IntegrityError("INSERT ...", params=None, orig=Exception("duplicate"))

        monkeypatch.setattr(async_session, "commit", _raise_integrity_error)

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as conflict_client:
            response = await conflict_client.post(
                CHECKIN_API,
                params={"location": "sick", "date": work_date.isoformat()},
            )

        app.dependency_overrides.clear()

        assert response.status_code == 409

        # Restore commit/get_by_date so we can read the real persisted state.
        monkeypatch.undo()

        # No duplicate row, and the already-persisted entry is unchanged.
        result = await async_session.execute(
            select(WorkEntry).where(WorkEntry.work_date == work_date)
        )
        rows = list(result.scalars().all())
        assert len(rows) == 1
        assert rows[0].id == seeded_id
        assert rows[0].location == seeded_location == WorkLocation.HOME.value


# ---------------------------------------------------------------------------
# Task 7.5 - 503 database-availability integration (Requirements 8.1-8.4)
# ---------------------------------------------------------------------------


class _FailingSession:
    """A stand-in ``AsyncSession`` whose DB operations raise a connectivity error.

    The check-in handler reaches the database through
    ``EntryRepository.get_by_date`` -> ``session.execute`` first, which is where
    a connectivity failure surfaces. ``commit``/``rollback`` are provided so any
    later call path also fails cleanly rather than with an ``AttributeError``.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def execute(self, *args: object, **kwargs: object) -> object:
        raise self._error

    async def get(self, *args: object, **kwargs: object) -> object:
        raise self._error

    async def commit(self) -> None:
        raise self._error

    async def rollback(self) -> None:
        return None


def _operational_error() -> OperationalError:
    return OperationalError(
        "SELECT ...", params=None, orig=Exception("connection refused")
    )


def _client_raising(error: Exception) -> AsyncClient:
    """Build an ``AsyncClient`` whose DB session raises ``error`` on use."""
    app = create_app()

    async def _override_get_session() -> AsyncGenerator[_FailingSession, None]:
        yield _FailingSession(error)

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_settings] = settings_override
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport, base_url="http://test", headers=AUTH_HEADERS
    )


class TestDatabaseUnavailableReturns503:
    """Connectivity failures at the session boundary become 503, not 2xx."""

    async def test_operational_error_returns_503_distinct_body(self) -> None:
        # Requirements 8.2/8.3: non-2xx with a distinct machine-readable body
        # that tells an outage apart from a client (401/409/422) error.
        async with _client_raising(_operational_error()) as db_client:
            response = await db_client.post(CHECKIN_API)

        assert response.status_code == 503
        assert not (200 <= response.status_code < 300)
        assert response.json() == {"detail": "Database unavailable"}

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionRefusedError("connection refused"),
            OSError("network is unreachable"),
            TimeoutError("connect timeout"),
        ],
        ids=["connection_refused", "os_error", "timeout_error"],
    )
    async def test_connection_errors_translate_to_503_at_boundary(
        self, error: OSError, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Requirement 8.1: a connect timeout / refused connection surfaces as a
        # 503 through the real ``get_session`` boundary (not overridden here),
        # so the execute-time wrapping into DatabaseUnavailableError is covered.
        app = create_app()

        @asynccontextmanager
        async def _failing_session_context() -> AsyncGenerator[_FailingSession, None]:
            yield _FailingSession(error)

        monkeypatch.setattr(
            "backend.database.get_session_factory", lambda: _failing_session_context
        )
        app.dependency_overrides[get_settings] = settings_override

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as db_client:
            response = await db_client.post(CHECKIN_API)

        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}

    async def test_no_partial_write_persisted_when_db_unavailable(
        self, async_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Requirement 8.4: a write that fails partway because the database
        # becomes unreachable during the write leaves persisted data unchanged,
        # so no partial entry is persisted.
        work_date = local_date()

        # Force the create path, then make the insert's commit fail with a
        # connectivity error. The handler must not leave a partial row behind.
        async def _always_missing(self: EntryRepository, wd: object) -> None:
            return None

        monkeypatch.setattr(EntryRepository, "get_by_date", _always_missing)

        async def _raise_operational_error() -> None:
            raise _operational_error()

        monkeypatch.setattr(async_session, "commit", _raise_operational_error)

        app = create_app()

        async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
            yield async_session

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_settings] = settings_override

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=AUTH_HEADERS
        ) as db_client:
            response = await db_client.post(
                CHECKIN_API, params={"date": work_date.isoformat()}
            )

        app.dependency_overrides.clear()

        assert response.status_code == 503
        assert not (200 <= response.status_code < 300)

        # Restore commit so we can read the real persisted state back.
        monkeypatch.undo()
        await async_session.rollback()
        assert await _count_rows(async_session) == 0


# ---------------------------------------------------------------------------
# Task 7.6 - Explicit non-real-date and Local_Date boundary examples
# ---------------------------------------------------------------------------


class TestNonRealDateExamples:
    """Pattern-valid but impossible dates are rejected; Local_Date is accepted."""

    @pytest.mark.parametrize("bad_date", ["2025-02-30", "2025-13-01"])
    async def test_impossible_but_pattern_valid_date_returns_422(
        self, client: AsyncClient, async_session: AsyncSession, bad_date: str
    ) -> None:
        # Requirement 5.4: dates matching YYYY-MM-DD that are not real calendar
        # dates (Feb 30, month 13) are rejected with 422 and no write.
        response = await client.post(CHECKIN_API, params={"date": bad_date})

        assert response.status_code == 422
        assert await _count_rows(async_session) == 0

    async def test_local_date_is_accepted(
        self, client: AsyncClient, async_session: AsyncSession
    ) -> None:
        # Requirement 5.2: date == Local_Date is valid (not rejected as future).
        today = local_date()
        response = await client.post(CHECKIN_API, params={"date": today.isoformat()})

        assert response.status_code == 201
        body = response.json()
        assert body["work_date"] == today.isoformat()
        assert await _count_rows(async_session) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
