"""Async data-access layer for :class:`~backend.models.WorkEntry`.

``EntryRepository`` wraps a SQLAlchemy :class:`AsyncSession` and provides the
CRUD and query operations used by the service layer. Month/year range queries
use explicit date-range filters (``>= first_day`` and ``< first_day_of_next``)
rather than ``extract()`` so they work identically on SQLite (used in tests)
and PostgreSQL (production).
"""

from datetime import date

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

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
    """Return the first day of the month following ``year``/``month``.

    The entries contract accepts any ``year >= 2000`` with no upper bound
    (Requirement 5.2), but Python's :class:`datetime.date` only supports years
    up to 9999. For the terminal boundary (December 9999) the "first day of the
    next month" would overflow, so :data:`datetime.date.max` is returned as an
    inclusive-of-the-last-representable-day ceiling instead of raising.
    """
    if year >= date.max.year and month == 12:
        return date.max
    if month == 12:
        return date(year + 1, 1, 1)
    return date(year, month + 1, 1)


def _first_of_next_year(year: int) -> date:
    """Return the first day of the year following ``year``.

    As with :func:`_first_of_next_month`, the year following 9999 is not
    representable, so :data:`datetime.date.max` is used as the ceiling for the
    terminal year rather than raising ``ValueError``.
    """
    if year >= date.max.year:
        return date.max
    return date(year + 1, 1, 1)


def _before(column: Mapped[date], end: date) -> ColumnElement[bool]:
    """Build the upper-bound predicate for a half-open date range.

    Normally the range is half-open (``work_date < end``). When ``end`` is the
    terminal :data:`datetime.date.max` ceiling (returned by the helpers above
    for years at/after 9999), the last representable day must be *included*, so
    an inclusive ``<=`` comparison is used instead.
    """
    if end == date.max:
        return column <= end
    return column < end


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
            .where(WorkEntry.work_date >= start, _before(WorkEntry.work_date, end))
            .order_by(WorkEntry.work_date.asc())
        )
        return list(result.scalars().all())

    async def get_by_year(self, year: int) -> list[WorkEntry]:
        """Return all entries in ``year`` ordered by ``work_date`` ascending."""
        start = date(year, 1, 1)
        end = _first_of_next_year(year)
        result = await self._session.execute(
            select(WorkEntry)
            .where(WorkEntry.work_date >= start, _before(WorkEntry.work_date, end))
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
