"""Work-entry orchestration service.

``EntryService`` sits between the routers and the :class:`EntryRepository`,
implementing the upsert semantics required for logging a work location: at most
one :class:`~backend.models.WorkEntry` row exists per calendar day, and logging
the same date again updates the existing row rather than creating a duplicate.

The ``get_entries_for_month`` and ``delete_entry`` methods are thin delegations
to the repository.

Requirements: 1.2, 1.3, 4.2
"""

from datetime import date

from backend.models import WorkEntry
from backend.repository import EntryRepository
from backend.schemas import WorkEntryCreate, WorkLocation


class EntryService:
    """Orchestrates work-entry persistence with per-day upsert semantics."""

    def __init__(self, repo: EntryRepository) -> None:
        self._repo = repo

    async def upsert_entry(self, work_date: date, location: WorkLocation) -> WorkEntry:
        """Create or update the work entry for ``work_date``.

        Follows the ``upsert_entry`` pseudocode: consult
        :meth:`EntryRepository.get_by_date` first; if a row already exists for
        the date, update its location via :meth:`EntryRepository.update`;
        otherwise create a new row via :meth:`EntryRepository.create`.

        Postconditions:
            - Exactly one ``WorkEntry`` row exists for ``work_date``.
            - The returned entry has the supplied ``work_date`` and ``location``.
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
        return await self._repo.delete(entry_id)
