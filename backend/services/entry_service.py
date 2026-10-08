"""Business logic for work-location entries.

``EntryService`` orchestrates the :class:`~backend.repository.EntryRepository`
to implement the *upsert* behaviour required by the "one entry per calendar
day" rule, plus thin delegation for month queries and deletion. It contains no
database I/O of its own — all persistence goes through the repository.

Requirements: 1.2, 1.3, 4.2
"""

from datetime import date

from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkEntryCreate, WorkLocation


class EntryService:
    """Service layer for creating, updating, querying and deleting entries."""

    def __init__(self, repo: EntryRepository) -> None:
        self._repo = repo

    async def upsert_entry(self, work_date: date, location: WorkLocation) -> WorkEntry:
        """Create or update the entry for ``work_date`` (one row per date).

        Follows the ``upsert_entry`` pseudocode: look up any existing entry for
        the date; if one exists update its location, otherwise create a new
        row. The returned entry always has ``work_date == work_date`` and
        ``location == location``.
        """
        existing = await self._repo.get_by_date(work_date)

        if existing is not None:
            return await self._repo.update(existing.id, location)

        return await self._repo.create(
            WorkEntryCreate(work_date=work_date, location=location)
        )

    async def get_entries_for_month(self, year: int, month: int) -> list[WorkEntry]:
        """Return all entries for ``year``/``month`` ordered by ``work_date``."""
        return await self._repo.get_by_month(year, month)

    async def delete_entry(self, entry_id: int) -> None:
        """Delete the entry identified by ``entry_id``."""
        await self._repo.delete(entry_id)
