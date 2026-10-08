"""Failing tests for ``EntryService`` (TDD red phase — task 5.1).

These tests describe the behaviour of the yet-to-be-implemented
``backend.services.entry_service.EntryService``. They are expected to FAIL at
import time (``backend.services.entry_service`` does not exist yet) until task
5.2 implements it.

The service interface under test (from the design document)::

    class EntryService:
        def __init__(self, repo: EntryRepository) -> None: ...
        async def upsert_entry(
            self, work_date: date, location: WorkLocation
        ) -> WorkEntry: ...
        async def get_entries_for_month(
            self, year: int, month: int
        ) -> list[WorkEntry]: ...
        async def delete_entry(self, entry_id: int) -> None: ...

``EntryRepository`` is fully mocked with ``unittest.mock`` (``AsyncMock`` for the
async methods) so these tests isolate the service's orchestration logic — the
``upsert`` decision (create vs. update) and the thin delegation methods — from
any real database I/O.

Requirements: 1.2, 1.3, 4.2
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkLocation
from backend.services.entry_service import EntryService


def _entry(entry_id: int, work_date: date, location: str) -> WorkEntry:
    """Build a transient ``WorkEntry`` standing in for a persisted row."""
    return WorkEntry(id=entry_id, work_date=work_date, location=location)


def _mock_repo() -> MagicMock:
    """Return a mock ``EntryRepository`` with async methods stubbed out."""
    repo = MagicMock(spec=EntryRepository)
    repo.get_by_date = AsyncMock()
    repo.get_by_month = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# upsert_entry — update path (entry already exists for the date)
# ---------------------------------------------------------------------------


class TestUpsertEntryUpdatePath:
    @pytest.mark.asyncio
    async def test_calls_repo_update_when_entry_exists(self) -> None:
        work_date = date(2025, 6, 10)
        existing = _entry(42, work_date, "home")
        updated = _entry(42, work_date, "denmark")

        repo = _mock_repo()
        repo.get_by_date.return_value = existing
        repo.update.return_value = updated

        svc = EntryService(repo)
        await svc.upsert_entry(work_date, WorkLocation.DENMARK)

        repo.get_by_date.assert_awaited_once_with(work_date)
        repo.update.assert_awaited_once_with(existing.id, WorkLocation.DENMARK)
        repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_entry_with_correct_date_and_location_on_update(
        self,
    ) -> None:
        work_date = date(2025, 6, 10)
        existing = _entry(42, work_date, "home")
        updated = _entry(42, work_date, "denmark")

        repo = _mock_repo()
        repo.get_by_date.return_value = existing
        repo.update.return_value = updated

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.DENMARK)

        assert result.work_date == work_date
        assert result.location == "denmark"


# ---------------------------------------------------------------------------
# upsert_entry — create path (no entry exists for the date)
# ---------------------------------------------------------------------------


class TestUpsertEntryCreatePath:
    @pytest.mark.asyncio
    async def test_calls_repo_create_when_entry_missing(self) -> None:
        work_date = date(2025, 6, 11)
        created = _entry(7, work_date, "vacation")

        repo = _mock_repo()
        repo.get_by_date.return_value = None
        repo.create.return_value = created

        svc = EntryService(repo)
        await svc.upsert_entry(work_date, WorkLocation.VACATION)

        repo.get_by_date.assert_awaited_once_with(work_date)
        repo.create.assert_awaited_once()
        repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_receives_matching_date_and_location(self) -> None:
        work_date = date(2025, 6, 11)
        created = _entry(7, work_date, "vacation")

        repo = _mock_repo()
        repo.get_by_date.return_value = None
        repo.create.return_value = created

        svc = EntryService(repo)
        await svc.upsert_entry(work_date, WorkLocation.VACATION)

        # The create payload must carry the requested date and location.
        create_arg = repo.create.await_args.args[0]
        assert create_arg.work_date == work_date
        assert create_arg.location == WorkLocation.VACATION

    @pytest.mark.asyncio
    async def test_returns_entry_with_correct_date_and_location_on_create(
        self,
    ) -> None:
        work_date = date(2025, 6, 11)
        created = _entry(7, work_date, "vacation")

        repo = _mock_repo()
        repo.get_by_date.return_value = None
        repo.create.return_value = created

        svc = EntryService(repo)
        result = await svc.upsert_entry(work_date, WorkLocation.VACATION)

        assert result.work_date == work_date
        assert result.location == "vacation"


# ---------------------------------------------------------------------------
# delete_entry — thin delegation to the repository
# ---------------------------------------------------------------------------


class TestDeleteEntry:
    @pytest.mark.asyncio
    async def test_delegates_to_repo_delete(self) -> None:
        repo = _mock_repo()
        repo.delete.return_value = None

        svc = EntryService(repo)
        await svc.delete_entry(99)

        repo.delete.assert_awaited_once_with(99)


# ---------------------------------------------------------------------------
# get_entries_for_month — thin delegation to the repository
# ---------------------------------------------------------------------------


class TestGetEntriesForMonth:
    @pytest.mark.asyncio
    async def test_delegates_to_repo_get_by_month(self) -> None:
        entries = [
            _entry(1, date(2025, 6, 2), "denmark"),
            _entry(2, date(2025, 6, 3), "home"),
        ]
        repo = _mock_repo()
        repo.get_by_month.return_value = entries

        svc = EntryService(repo)
        result = await svc.get_entries_for_month(2025, 6)

        repo.get_by_month.assert_awaited_once_with(2025, 6)
        assert result == entries


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
