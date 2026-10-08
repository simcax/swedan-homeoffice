"""HTTP route handlers for work-location entries.

This router exposes CRUD endpoints for :class:`~backend.models.WorkEntry`
rows, mounted at ``/api/v1/entries`` by the app factory. Each handler wires an
:class:`~backend.repository.EntryRepository` into an
:class:`~backend.services.entry_service.EntryService` using the request-scoped
``AsyncSession`` yielded by :func:`backend.database.get_session`.

Error handling (per the design document):

* ``404 Not Found`` with ``{"detail": "Entry not found"}`` when a PATCH/DELETE
  targets an ``entry_id`` that does not exist (``EntryNotFoundError``).
* ``409 Conflict`` when a concurrent insert violates the ``work_date`` unique
  constraint (``IntegrityError``).
* ``422 Unprocessable Entity`` is produced automatically by FastAPI/Pydantic
  for malformed bodies, out-of-range query params, and future dates.

Requirements: 1.1, 1.2, 1.6, 3.1, 3.2, 3.3, 3.4, 4.2, 4.3, 4.4, 5.1, 5.4
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.repository import EntryNotFoundError, EntryRepository
from backend.schemas import WorkEntryCreate, WorkEntryResponse, WorkEntryUpdate
from backend.services.entry_service import EntryService

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])

_ENTRY_NOT_FOUND = "Entry not found"

# Query-parameter constraints. Out-of-range values produce a 422 response.
_YearParam = Annotated[
    int,
    Query(ge=2000, description="Calendar year (>= 2000)"),
]
_MonthParam = Annotated[
    int,
    Query(ge=1, le=12, description="Calendar month in the range 1-12"),
]
_Session = Annotated[AsyncSession, Depends(get_session)]


def _service(db: AsyncSession) -> EntryService:
    """Build an ``EntryService`` backed by the given session."""
    return EntryService(EntryRepository(db))


@router.get("", response_model=list[WorkEntryResponse])
async def list_entries(
    year: _YearParam,
    month: _MonthParam,
    db: _Session,
) -> list[WorkEntryResponse]:
    """Return all entries for ``year``/``month`` ordered ascending by date."""
    entries = await _service(db).get_entries_for_month(year, month)
    return [WorkEntryResponse.model_validate(entry) for entry in entries]


@router.post("", response_model=WorkEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: WorkEntryCreate,
    db: _Session,
) -> WorkEntryResponse:
    """Create or update (upsert) the entry for ``body.work_date``."""
    try:
        entry = await _service(db).upsert_entry(body.work_date, body.location)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry already exists for this date",
        ) from exc
    return WorkEntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=WorkEntryResponse)
async def update_entry(
    entry_id: int,
    body: WorkEntryUpdate,
    db: _Session,
) -> WorkEntryResponse:
    """Update the location of an existing entry."""
    repo = EntryRepository(db)
    try:
        entry = await repo.update(entry_id, body.location)
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_ENTRY_NOT_FOUND,
        ) from exc
    return WorkEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    db: _Session,
) -> None:
    """Delete an existing entry."""
    try:
        await _service(db).delete_entry(entry_id)
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_ENTRY_NOT_FOUND,
        ) from exc
