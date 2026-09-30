"""CRUD endpoints for work entries.

Exposes the ``/api/v1/entries`` router. Each handler wires an
:class:`EntryRepository` (bound to the request-scoped ``AsyncSession`` from the
``get_session`` dependency) into an :class:`EntryService`, keeping HTTP concerns
in this layer and business logic in the service/repository layers.

Error mapping (see design "Error Handling"):

* ``422`` — invalid request body (future ``work_date`` / unknown ``location`` /
  out-of-range query params). Handled automatically by FastAPI/Pydantic.
* ``404`` — PATCH/DELETE of a nonexistent id → ``{"detail": "Entry not found"}``.
* ``409`` — unique-constraint violation on the ``work_date`` column (race
  condition fallback around the upsert guard).

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

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[WorkEntryResponse])
async def list_entries(
    db: SessionDep,
    year: Annotated[int, Query(ge=2000, le=2099)],
    month: Annotated[int, Query(ge=1, le=12)],
) -> list[WorkEntryResponse]:
    """Return all entries for ``year``/``month`` ordered ascending by date."""
    service = EntryService(EntryRepository(db))
    entries = await service.get_entries_for_month(year, month)
    return [WorkEntryResponse.model_validate(entry) for entry in entries]


@router.post("", response_model=WorkEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_entry(
    body: WorkEntryCreate,
    db: SessionDep,
) -> WorkEntryResponse:
    """Create (or upsert) a work entry for the given date."""
    service = EntryService(EntryRepository(db))
    try:
        entry = await service.upsert_entry(body.work_date, body.location)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry already exists for this date",
        ) from exc
    return WorkEntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=WorkEntryResponse)
async def update_entry(
    entry_id: int,
    body: WorkEntryUpdate,
    db: SessionDep,
) -> WorkEntryResponse:
    """Update an existing entry's location, leaving ``work_date`` unchanged."""
    repo = EntryRepository(db)
    try:
        entry = await repo.update(entry_id, body.location)
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        ) from exc
    return WorkEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    db: SessionDep,
) -> None:
    """Delete an existing entry."""
    service = EntryService(EntryRepository(db))
    try:
        await service.delete_entry(entry_id)
    except EntryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entry not found",
        ) from exc
