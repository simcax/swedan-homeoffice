"""Property-based tests for the geofence check-in write path (task 6).

These tests cover the *write-path* correctness properties of the
``POST /api/v1/checkin`` feature (design "Correctness Properties" 4-9 and 14):
bare-check-in defaulting, create-on-empty-date, special-day protection,
working-location overwrite, idempotence, the at-most-one-entry-per-date
invariant, and the HTTP response contract.

Because ``hypothesis`` drives many examples per test function while
pytest-asyncio fixtures are function-scoped, each generated example builds its
*own* fresh in-memory SQLite database so examples are fully independent. This
mirrors the isolation pattern in ``test_entry_repository_properties.py``.

Properties 4, 5, 6, 7, 8, 9 drive the service/repository directly against a
fresh DB per example; property 14 drives the endpoint over
``httpx.AsyncClient`` / ``ASGITransport`` against a fresh DB per example,
mirroring ``test_entries_router.py`` (``create_app()`` + ``get_session`` /
``get_settings`` overrides).

Generators follow the design: ``WorkLocation`` via
``st.sampled_from(list(WorkLocation))`` and valid in-range dates via
``st.dates(min_value=date(2000, 1, 1), max_value=today)``.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime

from httpx import ASGITransport, AsyncClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings
from backend.database import get_session
from backend.main import create_app
from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkLocation
from backend.services.checkin_resolver import local_date
from backend.services.entry_service import EntryService

from .conftest import AUTH_HEADERS, settings_override

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

CHECKIN_API = "/api/v1/checkin"

# Allowed values, used by generators throughout.
_LOCATIONS = list(WorkLocation)
_SPECIAL_LOCATIONS = [WorkLocation.VACATION, WorkLocation.SICK]
_WORKING_LOCATIONS = [WorkLocation.HOME, WorkLocation.DENMARK]

# A fixed "today" so generated dates stay valid regardless of the wall clock,
# while still exercising the full in-range date space.
_TODAY = date(2025, 6, 15)
_valid_dates = st.dates(min_value=date(2000, 1, 1), max_value=_TODAY)


@asynccontextmanager
async def _fresh_engine_session() -> AsyncGenerator[
    tuple[object, async_sessionmaker[AsyncSession]], None
]:
    """Yield a fresh in-memory engine + session factory for one example.

    The schema is created from the ORM metadata up front and the engine is
    disposed on exit, so every example starts from an empty database.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(WorkEntry.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        yield engine, session_factory
    finally:
        await engine.dispose()


async def _row_count_for_date(session: AsyncSession, work_date: date) -> int:
    """Return how many ``WorkEntry`` rows exist for ``work_date``."""
    result = await session.execute(
        select(func.count())
        .select_from(WorkEntry)
        .where(WorkEntry.work_date == work_date)
    )
    return int(result.scalar_one())


async def _total_rows(session: AsyncSession) -> list[WorkEntry]:
    """Return all persisted ``WorkEntry`` rows."""
    result = await session.execute(select(WorkEntry))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Property 4: Bare check-in creates a Local_Date denmark entry
# ---------------------------------------------------------------------------


class TestBareCheckInCreatesLocalDateDenmark:
    # Feature: geofence-checkin-api, Property 4: Bare check-in creates a
    # Local_Date denmark entry. For any starting database state with no entry
    # for the Local_Date, a check-in with no location and no date creates
    # exactly one Work_Entry whose work_date equals the Local_Date and whose
    # location equals denmark.
    @given(seed=st.integers())
    @settings(max_examples=100, deadline=None)
    def test_bare_checkin_creates_local_date_denmark(self, seed: int) -> None:
        """**Validates: Requirements 1.2**"""

        async def scenario() -> None:
            app = create_app()

            async with _fresh_engine_session() as (_engine, session_factory):

                async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
                    async with session_factory() as session:
                        yield session

                app.dependency_overrides[get_session] = _override_get_session
                app.dependency_overrides[get_settings] = settings_override

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers=AUTH_HEADERS,
                ) as client:
                    # No location, no date -> defaults to denmark on Local_Date.
                    response = await client.post(CHECKIN_API)

                app.dependency_overrides.clear()

                assert response.status_code == 201
                body = response.json()
                expected_date = local_date()
                assert body["work_date"] == expected_date.isoformat()
                assert body["location"] == WorkLocation.DENMARK.value

                # Exactly one row exists, and it is the one just created.
                async with session_factory() as session:
                    rows = await _total_rows(session)
                    assert len(rows) == 1
                    assert rows[0].work_date == expected_date
                    assert rows[0].location == WorkLocation.DENMARK.value

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 5: Check-in on an empty date creates the resolved entry
# ---------------------------------------------------------------------------


class TestCreateOnEmptyDate:
    # Feature: geofence-checkin-api, Property 5: Check-in on an empty date
    # creates the resolved entry. For any resolved request (date, location)
    # where no Work_Entry exists for date, the check-in creates exactly one
    # Work_Entry for date whose location equals the resolved location.
    @given(work_date=_valid_dates, location=st.sampled_from(_LOCATIONS))
    @settings(max_examples=100, deadline=None)
    def test_create_on_empty_date(
        self, work_date: date, location: WorkLocation
    ) -> None:
        """**Validates: Requirements 4.1**"""

        async def scenario() -> None:
            async with _fresh_engine_session() as (_engine, session_factory):
                async with session_factory() as session:
                    service = EntryService(EntryRepository(session))
                    entry = await service.upsert_entry(work_date, location)

                    assert entry.work_date == work_date
                    assert entry.location == location.value

                async with session_factory() as session:
                    assert await _row_count_for_date(session, work_date) == 1
                    rows = await _total_rows(session)
                    assert len(rows) == 1
                    assert rows[0].location == location.value

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 6: Special-day protection preserves the stored entry
# ---------------------------------------------------------------------------


class TestSpecialDayProtection:
    # Feature: geofence-checkin-api, Property 6: Special-day protection
    # preserves the stored entry. For any target date whose existing
    # Work_Entry is a Special_Day (vacation or sick), and for any resolved
    # request location (ranging over all four WorkLocation values), the
    # check-in leaves that entry's location, work_date, and created_at
    # unchanged, creates no additional Work_Entry, and leaves exactly one row.
    @given(
        work_date=_valid_dates,
        seeded=st.sampled_from(_SPECIAL_LOCATIONS),
        incoming=st.sampled_from(_LOCATIONS),
    )
    @settings(max_examples=100, deadline=None)
    def test_special_day_is_preserved(
        self,
        work_date: date,
        seeded: WorkLocation,
        incoming: WorkLocation,
    ) -> None:
        """**Validates: Requirements 4.2, 4.4**"""

        async def scenario() -> None:
            app = create_app()

            async with _fresh_engine_session() as (_engine, session_factory):
                # Seed an existing Special_Day entry for the target date.
                async with session_factory() as session:
                    repo = EntryRepository(session)
                    await EntryService(repo).upsert_entry(work_date, seeded)
                    existing = await repo.get_by_date(work_date)
                    original_id = existing.id
                    original_created_at = existing.created_at
                    original_location = existing.location

                async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
                    async with session_factory() as session:
                        yield session

                app.dependency_overrides[get_session] = _override_get_session
                app.dependency_overrides[get_settings] = settings_override

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers=AUTH_HEADERS,
                ) as client:
                    response = await client.post(
                        CHECKIN_API,
                        params={
                            "location": incoming.value,
                            "date": work_date.isoformat(),
                        },
                    )

                app.dependency_overrides.clear()

                # Unchanged special-day -> 200 with the stored values.
                assert response.status_code == 200
                body = response.json()
                assert body["location"] == original_location
                assert body["work_date"] == work_date.isoformat()

                # The stored entry is unchanged and still the sole row.
                async with session_factory() as session:
                    rows = await _total_rows(session)
                    assert len(rows) == 1
                    row = rows[0]
                    assert row.id == original_id
                    assert row.location == original_location
                    assert row.work_date == work_date
                    assert row.created_at == original_created_at

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 7: Working-location entries are overwritten
# ---------------------------------------------------------------------------


class TestWorkingLocationOverwrite:
    # Feature: geofence-checkin-api, Property 7: Working-location entries are
    # overwritten. For any target date whose existing Work_Entry has a
    # Working_Location (home or denmark), and for any resolved request
    # location, the check-in sets that entry's location to the resolved
    # location and leaves exactly one row for that date.
    @given(
        work_date=_valid_dates,
        seeded=st.sampled_from(_WORKING_LOCATIONS),
        incoming=st.sampled_from(_LOCATIONS),
    )
    @settings(max_examples=100, deadline=None)
    def test_working_location_is_overwritten(
        self,
        work_date: date,
        seeded: WorkLocation,
        incoming: WorkLocation,
    ) -> None:
        """**Validates: Requirements 4.3**"""

        async def scenario() -> None:
            app = create_app()

            async with _fresh_engine_session() as (_engine, session_factory):
                # Seed an existing Working_Location entry for the target date.
                async with session_factory() as session:
                    await EntryService(EntryRepository(session)).upsert_entry(
                        work_date, seeded
                    )

                async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
                    async with session_factory() as session:
                        yield session

                app.dependency_overrides[get_session] = _override_get_session
                app.dependency_overrides[get_settings] = settings_override

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers=AUTH_HEADERS,
                ) as client:
                    response = await client.post(
                        CHECKIN_API,
                        params={
                            "location": incoming.value,
                            "date": work_date.isoformat(),
                        },
                    )

                app.dependency_overrides.clear()

                # Updating an existing working-location row -> 200, new value.
                assert response.status_code == 200
                body = response.json()
                assert body["location"] == incoming.value
                assert body["work_date"] == work_date.isoformat()

                async with session_factory() as session:
                    rows = await _total_rows(session)
                    assert len(rows) == 1
                    assert rows[0].location == incoming.value
                    assert rows[0].work_date == work_date

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 8: Check-in idempotence
# ---------------------------------------------------------------------------


class TestCheckInIdempotence:
    # Feature: geofence-checkin-api, Property 8: Check-in idempotence. For any
    # resolved request (date, location) and for any starting database state,
    # applying the check-in twice in succession (with no intervening change)
    # produces the same persisted Work_Entry (work_date and location) as
    # applying it once, and leaves exactly one row for that date.
    @given(work_date=_valid_dates, location=st.sampled_from(_LOCATIONS))
    @settings(max_examples=100, deadline=None)
    def test_checkin_is_idempotent(
        self, work_date: date, location: WorkLocation
    ) -> None:
        """**Validates: Requirements 4.5**"""

        async def scenario() -> None:
            async with _fresh_engine_session() as (_engine, session_factory):
                # Apply the same upsert twice with no intervening change.
                async with session_factory() as session:
                    service = EntryService(EntryRepository(session))
                    first = await service.upsert_entry(work_date, location)
                    first_id = first.id
                    second = await service.upsert_entry(work_date, location)

                    assert second.id == first_id
                    assert second.work_date == work_date == first.work_date
                    assert second.location == location.value == first.location

                async with session_factory() as session:
                    assert await _row_count_for_date(session, work_date) == 1
                    rows = await _total_rows(session)
                    assert len(rows) == 1
                    assert rows[0].work_date == work_date
                    assert rows[0].location == location.value

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 9: At-most-one entry per calendar date
# ---------------------------------------------------------------------------


class TestAtMostOneEntryPerDate:
    # Feature: geofence-checkin-api, Property 9: At-most-one entry per calendar
    # date. For any sequence of resolved check-in requests applied to an
    # initially empty database, after processing there is at most one
    # Work_Entry per work_date.
    @given(
        requests=st.lists(
            st.tuples(_valid_dates, st.sampled_from(_LOCATIONS)),
            min_size=0,
            max_size=25,
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_at_most_one_entry_per_date(
        self, requests: list[tuple[date, WorkLocation]]
    ) -> None:
        """**Validates: Requirements 7.2**"""

        async def scenario() -> None:
            async with _fresh_engine_session() as (_engine, session_factory):
                async with session_factory() as session:
                    service = EntryService(EntryRepository(session))
                    for work_date, location in requests:
                        await service.upsert_entry(work_date, location)

                async with session_factory() as session:
                    rows = await _total_rows(session)
                    seen_dates = [row.work_date for row in rows]
                    # No duplicate work_date values (at most one row per date).
                    assert len(seen_dates) == len(set(seen_dates))
                    # And the set of dates equals the distinct requested dates.
                    assert set(seen_dates) == {work_date for work_date, _ in requests}

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Property 14: Response contract
# ---------------------------------------------------------------------------

_EXPECTED_RESPONSE_FIELDS = {"id", "work_date", "location", "created_at", "updated_at"}
_LOCATION_VALUES = {member.value for member in WorkLocation}


def _assert_response_contract(body: dict) -> None:
    """Assert ``body`` matches the check-in response contract exactly."""
    # Exactly these fields and no others.
    assert set(body.keys()) == _EXPECTED_RESPONSE_FIELDS

    # id: positive integer.
    assert isinstance(body["id"], int)
    assert not isinstance(body["id"], bool)
    assert body["id"] > 0

    # work_date: ISO YYYY-MM-DD date string.
    assert isinstance(body["work_date"], str)
    parsed_date = date.fromisoformat(body["work_date"])
    assert parsed_date.isoformat() == body["work_date"]

    # location: one of the WorkLocation string values.
    assert isinstance(body["location"], str)
    assert body["location"] in _LOCATION_VALUES

    # created_at / updated_at: ISO 8601 date-time strings.
    for field_name in ("created_at", "updated_at"):
        assert isinstance(body[field_name], str)
        # Accept a trailing ``Z`` as a UTC designator for robustness.
        datetime.fromisoformat(body[field_name].replace("Z", "+00:00"))


class TestResponseContract:
    # Feature: geofence-checkin-api, Property 14: Response contract. For any
    # successful check-in (create, update, or unchanged special-day), the JSON
    # response body contains exactly the fields id, work_date, location,
    # created_at, updated_at and no others, with id a positive integer,
    # work_date an ISO YYYY-MM-DD string, location one of the WorkLocation
    # string values, and created_at/updated_at ISO 8601 date-time strings; the
    # status code is 201 when a new entry is created and 200 when an existing
    # entry is updated or left unchanged.
    @given(
        work_date=_valid_dates,
        seeded=st.one_of(st.none(), st.sampled_from(_LOCATIONS)),
        incoming=st.sampled_from(_LOCATIONS),
    )
    @settings(max_examples=100, deadline=None)
    def test_response_contract(
        self,
        work_date: date,
        seeded: WorkLocation | None,
        incoming: WorkLocation,
    ) -> None:
        """**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**"""

        async def scenario() -> None:
            app = create_app()

            async with _fresh_engine_session() as (_engine, session_factory):
                # Optionally seed an existing entry to exercise the create (201)
                # and update/unchanged (200) branches.
                is_special_seed = seeded in _SPECIAL_LOCATIONS
                if seeded is not None:
                    async with session_factory() as session:
                        await EntryService(EntryRepository(session)).upsert_entry(
                            work_date, seeded
                        )

                async def _override_get_session() -> AsyncGenerator[AsyncSession, None]:
                    async with session_factory() as session:
                        yield session

                app.dependency_overrides[get_session] = _override_get_session
                app.dependency_overrides[get_settings] = settings_override

                transport = ASGITransport(app=app)
                async with AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers=AUTH_HEADERS,
                ) as client:
                    response = await client.post(
                        CHECKIN_API,
                        params={
                            "location": incoming.value,
                            "date": work_date.isoformat(),
                        },
                    )

                app.dependency_overrides.clear()

                body = response.json()
                _assert_response_contract(body)

                # 201 on create (no prior row); 200 on update or unchanged.
                if seeded is None:
                    assert response.status_code == 201
                else:
                    assert response.status_code == 200

                # Unchanged special-day returns the stored (seeded) location;
                # otherwise the resolved incoming location is persisted.
                if is_special_seed:
                    assert body["location"] == seeded.value
                else:
                    assert body["location"] == incoming.value

        asyncio.run(scenario())
