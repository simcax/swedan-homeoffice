"""Failing tests for ``EntryRepository`` (TDD red phase — task 3.1).

These tests describe the behaviour of the yet-to-be-implemented
``backend.repository.EntryRepository``. They are expected to FAIL at import
time (``backend.repository`` does not exist yet) until task 3.2 implements it.

The repository interface under test (from the design document)::

    class EntryRepository:
        def __init__(self, session: AsyncSession) -> None: ...
        async def get_by_date(self, date: date) -> WorkEntry | None: ...
        async def get_by_month(self, year: int, month: int) -> list[WorkEntry]: ...
        async def get_by_year(self, year: int) -> list[WorkEntry]: ...
        async def create(self, entry: WorkEntryCreate) -> WorkEntry: ...
        async def update(self, entry_id: int, location: WorkLocation) -> WorkEntry: ...
        async def delete(self, entry_id: int) -> None: ...

Requirements: 3.2, 4.2, 4.3, 5.2, 10.1, 10.2
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repository import EntryRepository
from backend.schemas import WorkEntryCreate, WorkLocation

# ---------------------------------------------------------------------------
# get_by_date
# ---------------------------------------------------------------------------


class TestGetByDate:
    async def test_returns_none_when_no_entry_exists(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        result = await repo.get_by_date(date(2025, 6, 10))
        assert result is None

    async def test_returns_entry_when_it_exists(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 10), location=WorkLocation.DENMARK)
        )

        result = await repo.get_by_date(date(2025, 6, 10))

        assert result is not None
        assert result.work_date == date(2025, 6, 10)
        assert result.location == WorkLocation.DENMARK.value


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_inserts_row_and_returns_entry(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)

        entry = await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 10), location=WorkLocation.HOME)
        )

        assert entry.id is not None
        assert entry.work_date == date(2025, 6, 10)
        assert entry.location == WorkLocation.HOME.value

    async def test_created_row_is_retrievable(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 1, 15), location=WorkLocation.SICK)
        )

        fetched = await repo.get_by_date(date(2025, 1, 15))

        assert fetched is not None
        assert fetched.location == WorkLocation.SICK.value


# ---------------------------------------------------------------------------
# get_by_month
# ---------------------------------------------------------------------------


class TestGetByMonth:
    async def test_returns_empty_list_when_none_exist(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        result = await repo.get_by_month(2025, 6)
        assert result == []

    async def test_returns_entries_ordered_ascending_by_work_date(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        # Insert out of order.
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 20), location=WorkLocation.HOME)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 5), location=WorkLocation.DENMARK)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 12), location=WorkLocation.VACATION)
        )

        result = await repo.get_by_month(2025, 6)

        work_dates = [e.work_date for e in result]
        assert work_dates == [
            date(2025, 6, 5),
            date(2025, 6, 12),
            date(2025, 6, 20),
        ]

    async def test_excludes_entries_from_other_months(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 5, 31), location=WorkLocation.HOME)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 1), location=WorkLocation.DENMARK)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 7, 1), location=WorkLocation.HOME)
        )

        result = await repo.get_by_month(2025, 6)

        assert [e.work_date for e in result] == [date(2025, 6, 1)]


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_changes_location_and_leaves_work_date_unchanged(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        created = await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 10), location=WorkLocation.HOME)
        )

        updated = await repo.update(created.id, WorkLocation.DENMARK)

        assert updated.id == created.id
        assert updated.location == WorkLocation.DENMARK.value
        assert updated.work_date == date(2025, 6, 10)

    async def test_update_is_persisted(self, async_session: AsyncSession) -> None:
        repo = EntryRepository(async_session)
        created = await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 10), location=WorkLocation.HOME)
        )

        await repo.update(created.id, WorkLocation.SICK)
        fetched = await repo.get_by_date(date(2025, 6, 10))

        assert fetched is not None
        assert fetched.location == WorkLocation.SICK.value


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_removes_row_so_get_by_date_returns_none(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        created = await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 10), location=WorkLocation.DENMARK)
        )

        await repo.delete(created.id)

        assert await repo.get_by_date(date(2025, 6, 10)) is None


# ---------------------------------------------------------------------------
# get_by_year
# ---------------------------------------------------------------------------


class TestGetByYear:
    async def test_returns_empty_list_when_none_exist(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        result = await repo.get_by_year(2025)
        assert result == []

    async def test_returns_all_entries_for_year_across_all_months(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 1, 10), location=WorkLocation.HOME)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 6, 15), location=WorkLocation.DENMARK)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 12, 31), location=WorkLocation.SICK)
        )
        # An entry in a different year must be excluded.
        await repo.create(
            WorkEntryCreate(work_date=date(2024, 12, 31), location=WorkLocation.HOME)
        )

        result = await repo.get_by_year(2025)

        assert len(result) == 3
        assert {e.work_date for e in result} == {
            date(2025, 1, 10),
            date(2025, 6, 15),
            date(2025, 12, 31),
        }

    async def test_excludes_entries_from_other_years(
        self, async_session: AsyncSession
    ) -> None:
        repo = EntryRepository(async_session)
        await repo.create(
            WorkEntryCreate(work_date=date(2023, 3, 1), location=WorkLocation.HOME)
        )
        await repo.create(
            WorkEntryCreate(work_date=date(2025, 3, 1), location=WorkLocation.DENMARK)
        )

        result = await repo.get_by_year(2025)

        assert [e.work_date for e in result] == [date(2025, 3, 1)]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
