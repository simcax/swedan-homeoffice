"""Async data-access layer for :class:`~backend.models.WorkEntry`.

``EntryRepository`` wraps a SQLAlchemy :class:`AsyncSession` and provides the
CRUD and query operations used by the service layer. Month/year range queries
use explicit date-range filters (``>= first_day`` and ``< first_day_of_next``)
rather than ``extract()`` so they work identically on SQLite (used in tests)
and PostgreSQL (production).
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import WorkEntry
from backend.schemas import WorkEntryCreate, WorkLocation


class EntryNotFoundError(Exception):
    """Raised when an operation targets an ``entry_id`` that does not exist.

    Routers translate this into an HTTP ``404 Not Found`` response.
    """

    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"Entry not found: {entry_id}")


def _first_of_next_month(year: int, month: int) -> date:
    """Return the first day of the month following ``year``/``month``."""
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


class EntryRepository:
    """Async CRUD/query operations for ``WorkEntry`` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_date(self, work_date: date) -> WorkEntry | None:
        """Return the entry for ``work_date`` or ``None`` if none exists."""
        result = await self._session.execute(
            select(WorkEntry).where(WorkEntry.work_date == work_date)
        )
        return result.scalar_one_or_none()

    async def get_by_month(self, year: int, month: int) -> list[WorkEntry]:
        """Return all entries in ``year``/``month`` ordered by ``work_date`` asc."""
        start = date(year, month, 1)
        end = _first_of_next_month(year, month)
        result = await self._session.execute(
            select(WorkEntry)
            .where(WorkEntry.work_date >= start, WorkEntry.work_date < end)
            .order_by(WorkEntry.work_date.asc())
        )
        return list(result.scalars().all())

    async def get_by_year(self, year: int) -> list[WorkEntry]:
        """Return all entries in ``year`` ordered by ``work_date`` ascending."""
        start = date(year, 1, 1)
        end = date(year + 1, 1, 1)
        result = await self._session.execute(
            select(WorkEntry)
            .where(WorkEntry.work_date >= start, WorkEntry.work_date < end)
            .order_by(WorkEntry.work_date.asc())
        )
        return list(result.scalars().all())

    async def create(self, entry: WorkEntryCreate) -> WorkEntry:
        """Insert a new ``WorkEntry`` and return the persisted row."""
        row = WorkEntry(
            work_date=entry.work_date,
            location=entry.location.value,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def update(self, entry_id: int, location: WorkLocation) -> WorkEntry:
        """Update the location of an existing entry and return the updated row.

        Raises:
            EntryNotFoundError: if no entry with ``entry_id`` exists.
        """
        row = await self._session.get(WorkEntry, entry_id)
        if row is None:
            raise EntryNotFoundError(entry_id)
        row.location = location.value
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def delete(self, entry_id: int) -> None:
        """Delete an existing entry.

        Raises:
            EntryNotFoundError: if no entry with ``entry_id`` exists.
        """
        row = await self._session.get(WorkEntry, entry_id)
        if row is None:
            raise EntryNotFoundError(entry_id)
        await self._session.delete(row)
        await self._session.commit()
