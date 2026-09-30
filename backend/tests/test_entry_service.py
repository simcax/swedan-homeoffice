"""Failing tests for ``EntryService`` (TDD red phase — task 5.1).

These tests describe the behaviour of the yet-to-be-implemented
``backend.services.entry_service.EntryService``. They are expected to FAIL at
import time (``backend.services.entry_service`` does not exist yet) until task
5.2 implements it.

The service interface under test (from the design document)::

    class EntryService:
        def __init__(self, repo: EntryRepository) -> None: ...
        async def upsert_entry(self, work_date: date, location: WorkLocation) -> WorkEntry: ...
        async def get_entries_for_month(self, year: int, month: int) -> list[WorkEntry]: ...
        async def delete_entry(self, entry_id: int) -> None: ...

``EntryRepository`` is fully mocked with ``AsyncMock`` — no database is
required. The tests verify the ``upsert_entry`` call paths from the design
pseudocode: ``repo.get_by_date`` is consulted first; an existing entry routes
to ``repo.update(existing.id, location)`` while a missing entry routes to
``repo.create(...)``. ``delete_entry`` and ``get_entries_for_month`` are thin
delegations to the repository.

Requirements: 1.2, 1.3, 4.2
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkLocation
from backend.services.entry_service import EntryService


def _entry(entry_id: int, work_date: date, location: str) -> WorkEntry:
    """Build a transient ``WorkEntry`` used as a repository return value."""
    return WorkEntry(id=entry_id, work_date=work_date, location=location)


@pytest.fixture
def repo() -> AsyncMock:
    """Return an ``EntryRepository`` mock with async methods."""
    return AsyncMock(spec=EntryRepository)


# ---------------------------------------------------------------------------
# upsert_entry
# ---------------------------------------------------------------------------


class TestUpsertEntry:
    @pytest.mark.asyncio
    async def test_updates_existing_entry_when_get_by_date_returns_a_row(
        self, repo: AsyncMock
    ) -> None:
        work_date = date(2025, 6, 10)
        existing = _entry(42, work_date, "home")
        updated = _entry(42, work_date, "denmark")
        repo.get_by_date.return_value = existing
        repo.update.return_value = updated

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.DENMARK)

        repo.get_by_date.assert_awaited_once_with(work_date)
        repo.update.assert_awaited_once_with(existing.id, WorkLocation.DENMARK)
        repo.create.assert_not_awaited()
        assert result is updated

    @pytest.mark.asyncio
    async def test_creates_new_entry_when_get_by_date_returns_none(
        self, repo: AsyncMock
    ) -> None:
        work_date = date(2025, 6, 10)
        created = _entry(1, work_date, "denmark")
        repo.get_by_date.return_value = None
        repo.create.return_value = created

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.DENMARK)

        repo.get_by_date.assert_awaited_once_with(work_date)
        repo.create.assert_awaited_once()
        repo.update.assert_not_awaited()
        assert result is created

    @pytest.mark.asyncio
    async def test_returned_entry_has_correct_date_and_location_on_update_path(
        self, repo: AsyncMock
    ) -> None:
        work_date = date(2025, 3, 5)
        existing = _entry(7, work_date, "home")
        repo.get_by_date.return_value = existing
        repo.update.return_value = _entry(7, work_date, "sick")

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.SICK)

        assert result.work_date == work_date
        assert result.location == WorkLocation.SICK.value

    @pytest.mark.asyncio
    async def test_returned_entry_has_correct_date_and_location_on_create_path(
        self, repo: AsyncMock
    ) -> None:
        work_date = date(2025, 3, 5)
        repo.get_by_date.return_value = None
        repo.create.return_value = _entry(1, work_date, "vacation")

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.VACATION)

        assert result.work_date == work_date
        assert result.location == WorkLocation.VACATION.value


# ---------------------------------------------------------------------------
# delete_entry
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    @pytest.mark.asyncio
    async def test_delegates_to_repo_delete(self, repo: AsyncMock) -> None:
        repo.delete.return_value = None

        svc = EntryService(repo)
        result = await svc.delete_entry(99)

        repo.delete.assert_awaited_once_with(99)
        assert result is None


# ---------------------------------------------------------------------------
# get_entries_for_month
# ---------------------------------------------------------------------------


class TestGetEntriesForMonth:
    @pytest.mark.asyncio
    async def test_delegates_to_repo_get_by_month(self, repo: AsyncMock) -> None:
        entries = [
            _entry(1, date(2025, 6, 2), "denmark"),
            _entry(2, date(2025, 6, 3), "home"),
        ]
        repo.get_by_month.return_value = entries

        svc = EntryService(repo)
        result = await svc.get_entries_for_month(2025, 6)

        repo.get_by_month.assert_awaited_once_with(2025, 6)
        assert result == entries


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
