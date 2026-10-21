"""HTTP route handler for the geofence check-in endpoint.

This router exposes a single authenticated ``POST /api/v1/checkin`` endpoint
used by a mobile geofence automation (iOS Shortcuts, Tasker, etc.) to log a
work-location entry with no request body. It reuses the existing building
blocks rather than duplicating them:

* :func:`backend.services.checkin_resolver.resolve_location` /
  :func:`~backend.services.checkin_resolver.resolve_date` /
  :func:`~backend.services.checkin_resolver.local_date` /
  :func:`~backend.services.checkin_resolver.is_special_day` — the pure
  resolver/validation core (query-driven defaulting, Local_Date resolution,
  special-day predicate).
* :class:`backend.repository.EntryRepository` — read-only ``get_by_date`` for
  special-day protection and to distinguish create (201) from update (200).
* :class:`backend.services.entry_service.EntryService.upsert_entry` — the sole
  write path (Requirement 7.1).
* :class:`backend.schemas.WorkEntryResponse` — the response model.
* :func:`backend.database.get_session` — so connectivity failures surface as
  503 automatically via the handlers registered in ``create_app``.

The one new behaviour beyond a plain upsert is **special-day protection**: an
automated check-in must never overwrite an existing ``vacation``/``sick``
entry, so the handler reads the existing entry first and returns it unchanged
(status 200) when it is a Special_Day.

Error handling mirrors the established patterns:

* ``401`` — produced by the ``verify_api_key`` dependency attached at router
  inclusion (see ``create_app``); the handler never runs without a valid key.
* ``422`` — raised by ``resolve_location`` / ``resolve_date`` for invalid
  location values, malformed/non-real dates, out-of-range dates, and future
  dates, before any write occurs.
* ``409`` — a concurrent insert violating the ``work_date`` unique constraint
  raises ``IntegrityError``; the handler rolls back and raises 409 (mirroring
  ``entries.create_entry``).
* ``503`` — connectivity failures surface from ``get_session`` as
  ``DatabaseUnavailableError`` and are mapped to 503 by ``create_app``.

Requirements: 1.1, 1.2, 1.7, 4.1, 4.2, 4.3, 4.4, 6.1, 6.2, 6.3, 6.4, 6.5,
7.1, 7.2, 7.3, 8.2, 8.3, 8.4
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.repository import EntryRepository
from backend.schemas import WorkEntryResponse, WorkLocation
from backend.services.checkin_resolver import (
    is_special_day,
    local_date,
    resolve_date,
    resolve_location,
)
from backend.services.entry_service import EntryService

router = APIRouter(prefix="/api/v1", tags=["checkin"])

_Session = Annotated[AsyncSession, Depends(get_session)]
_LocationParam = Annotated[
    str | None,
    Query(description="Work location (default: denmark)"),
]
_DateParam = Annotated[
    str | None,
    Query(alias="date", description="Target date as YYYY-MM-DD (default: today)"),
]


@router.post("/checkin", response_model=WorkEntryResponse)
async def checkin(
    response: Response,
    db: _Session,
    location: _LocationParam = None,
    date_param: _DateParam = None,
) -> WorkEntryResponse:
    """Record a geofence check-in, upserting one entry for the target date.

    Accepts optional ``location`` and ``date`` query parameters and requires no
    request body (any body is ignored). The location defaults to ``denmark``
    and the date defaults to the Local_Date in ``Europe/Copenhagen``.

    Special-day protection: when an entry already exists for the target date
    and is a Special_Day (``vacation``/``sick``), it is returned unchanged with
    status 200 and no write is performed. Otherwise the entry is upserted via
    :meth:`EntryService.upsert_entry` — the sole write path — with status 201
    when a new row is created and 200 when an existing row is updated.
    """
    # Resolve and validate inputs before any database write. Invalid values
    # raise HTTPException(422) from the pure resolver layer, so no Work_Entry is
    # created or modified on a rejected request.
    resolved_location = resolve_location(location)
    resolved_date = resolve_date(date_param, local_date())

    repo = EntryRepository(db)

    # Read the existing entry first: this both powers special-day protection
    # and lets us distinguish a create (201) from an update (200) for the
    # single upsert write path.
    existing = await repo.get_by_date(resolved_date)

    # Special-day protection: never overwrite a manually-logged vacation/sick
    # day. Return the stored entry unchanged with status 200 (Requirements 4.2,
    # 4.4, 6.3). The model stores ``location`` as a plain string, so coerce it
    # to the WorkLocation enum before the special-day check.
    if existing is not None and is_special_day(WorkLocation(existing.location)):
        response.status_code = status.HTTP_200_OK
        return WorkEntryResponse.model_validate(existing)

    # Perform the create/update exclusively through the upsert service
    # (Requirement 7.1). A concurrent insert that violates the ``work_date``
    # unique constraint surfaces as IntegrityError -> 409 (Requirement 7.3).
    try:
        entry = await EntryService(repo).upsert_entry(resolved_date, resolved_location)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Entry already exists for this date",
        ) from exc

    # 201 when a new row was created, 200 when an existing row was updated.
    response.status_code = (
        status.HTTP_200_OK if existing is not None else status.HTTP_201_CREATED
    )
    return WorkEntryResponse.model_validate(entry)
