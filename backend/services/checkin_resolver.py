"""Pure resolver/validation core for the geofence check-in endpoint.

This module holds the small, pure, property-testable helpers behind the
``POST /api/v1/checkin`` endpoint: the resolved-request value object, the
``Europe/Copenhagen`` Local_Date computation, and the special-day predicate.
It performs no database or HTTP I/O so the logic can be exercised directly in
unit and property-based tests.

It reuses the existing :class:`~backend.schemas.WorkLocation` enum rather than
redefining the allowed location values.

Requirements: 2.1, 2.2, 2.3, 4.2, 4.4
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from backend.schemas import WorkLocation

# IANA timezone used to compute the Local_Date (CET/CEST, DST-aware).
_LOCAL_TZ = ZoneInfo("Europe/Copenhagen")

# Strict ISO 8601 calendar-date pattern: four-digit year, two-digit month and
# day separated by hyphens. Used to distinguish malformed/non-ISO text from a
# pattern-valid but non-real calendar date.
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Inclusive lower bound for an accepted target date.
_MIN_DATE = date(2000, 1, 1)

# Locations that represent manually-logged, non-working special days.
_SPECIAL_DAY_LOCATIONS = frozenset({WorkLocation.VACATION, WorkLocation.SICK})

# Work_Location used when the client does not specify a location.
_DEFAULT_LOCATION = WorkLocation.DENMARK


@dataclass(frozen=True)
class ResolvedCheckIn:
    """A fully resolved check-in request ready for the write path.

    Produced by the resolver/validation layer and passed to the upsert
    service. It is the pure, property-testable representation of a check-in.
    """

    work_date: date
    location: WorkLocation


def local_date(now: datetime | None = None) -> date:
    """Return the current calendar date in the ``Europe/Copenhagen`` timezone.

    When ``now`` is ``None`` the current instant is read in the local timezone
    via :func:`datetime.datetime.now`. When an aware ``now`` is injected (for
    deterministic testing) it is converted into the local timezone before the
    calendar date is taken. The conversion is DST-aware and resolves to exactly
    one calendar date, including across spring-forward/fall-back transitions
    and near local midnight.
    """
    if now is None:
        now = datetime.now(_LOCAL_TZ)
    return now.astimezone(_LOCAL_TZ).date()


def is_special_day(location: WorkLocation) -> bool:
    """Return ``True`` when ``location`` is a Special_Day (``vacation``/``sick``)."""
    return location in _SPECIAL_DAY_LOCATIONS


def resolve_location(raw: str | None) -> WorkLocation:
    """Resolve the request Work_Location from an optional query value.

    Returns the exactly-matching :class:`WorkLocation` when ``raw`` is a
    non-empty, case-sensitive exact match of one of the enum string values
    (``home``, ``denmark``, ``vacation``, ``sick``). Returns the
    Default_Location (``denmark``) when ``raw`` is ``None`` or the empty
    string. Raises :class:`fastapi.HTTPException` with status 422 for any
    non-empty value that is not an exact match, so no Work_Entry is created
    or modified.

    Requirements: 1.3, 1.5, 5.6
    """
    if raw is None or raw == "":
        return _DEFAULT_LOCATION
    try:
        return WorkLocation(raw)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in WorkLocation)
        raise HTTPException(
            status_code=422,
            detail=f"Location '{raw}' is not allowed; expected one of: {allowed}",
        ) from exc


def resolve_date(raw: str | None, today: date) -> date:
    """Resolve and validate the target date from an optional query value.

    Parses ``raw`` strictly against the ISO ``YYYY-MM-DD`` pattern (four-digit
    year, two-digit month and day separated by hyphens). Returns the passed
    ``today`` (the Local_Date) when ``raw`` is ``None`` or the empty string.

    Raises :class:`fastapi.HTTPException` with status 422 and a distinct
    ``detail`` message for each failure cause, so no Work_Entry is created or
    modified:

    - text that does not match the ``YYYY-MM-DD`` pattern -> invalid-format;
    - pattern-valid but non-real calendar dates (e.g. ``2025-02-30`` or a month
      outside ``01``-``12``) -> invalid-calendar-date;
    - dates earlier than ``2000-01-01`` -> out-of-range;
    - dates strictly later than ``today`` -> future-date.

    A resolved date equal to ``today`` is accepted (not treated as a future
    date).

    Requirements: 1.4, 1.6, 5.1, 5.2, 5.3, 5.4, 5.5
    """
    if raw is None or raw == "":
        parsed = today
    else:
        if _ISO_DATE_PATTERN.match(raw) is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Date '{raw}' is not a valid ISO 8601 date; "
                    "expected format YYYY-MM-DD"
                ),
            )
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Date '{raw}' is not a valid calendar date",
            ) from exc

    if parsed < _MIN_DATE:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Date '{parsed.isoformat()}' is out of the accepted range; "
                f"must be on or after {_MIN_DATE.isoformat()}"
            ),
        )
    if parsed > today:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Date '{parsed.isoformat()}' is in the future; "
                f"must be on or before {today.isoformat()}"
            ),
        )
    return parsed
